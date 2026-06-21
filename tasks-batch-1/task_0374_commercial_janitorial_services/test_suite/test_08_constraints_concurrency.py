"""Validation-priority precedence, boundary precision, cross-entity state
dependencies, temporal overlap, and compensating invariants
(difficulty rules 5, 6, 7, 8, 9).

Translates SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 priority_pair_validation_conflict,
boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap,
and compensating_invariant instances. Each instance carries >=2 tests.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, fixtures,
)
from test_helpers.test_users import TEST_USERS
from test_helpers.api_client import api_client

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]


# ===========================================================================
# Rule 5 instance A: state_before_referential_on_visit_start
# ===========================================================================
def test_visit_start_state_check_precedes_crew_referential(api):
    """PRD §2.6: "(7) whether the target resource is in a state from which the
    requested transition is defined, yielding `ERR_INVALID_STATE` (HTTP 409); and
    (8) the cross-entity business preconditions (account active, site active, crew
    available, callback visit completed, contract active) described throughout §3."

    Design: Difficulty/priority_pair_validation_conflict/state_before_referential_on_visit_start
    """
    _, site, crew = fixtures.setup_account_site_crew()
    # visit becomes terminal COMPLETED, then crew is deactivated
    visit = fixtures.create_completed_routine_visit(site["id"], crew["id"])
    validate_success(api.deactivate_crew(crew["id"], FS), 200)
    # both state (COMPLETED, not SCHEDULED) and crew INACTIVE fail; state wins
    resp = api.start_visit(visit["id"], FS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_visit_start_invalid_state_not_crew_inactive(api):
    """PRD §2.6: "they are evaluated in a fixed priority order so that the most
    fundamental failure is the one reported." PRD §2.6: "(7) ... yielding
    `ERR_INVALID_STATE` (HTTP 409); and (8) the cross-entity business
    preconditions (account active, site active, crew available ...)".

    Design: Difficulty/priority_pair_validation_conflict/state_before_referential_on_visit_start
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_completed_routine_visit(site["id"], crew["id"])
    validate_success(api.deactivate_crew(crew["id"], FS), 200)
    resp = api.start_visit(visit["id"], FS)
    error_data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert error_data["error_id"] != ApiErrorId.ERR_CREW_INACTIVE.value


# ===========================================================================
# Rule 5 instance B: state_before_safety_on_periodic_dispatch
# ===========================================================================
def test_periodic_dispatch_state_check_precedes_floor_safety(api):
    """PRD §2.6: "(7) whether the target resource is in a state from which the
    requested transition is defined, yielding `ERR_INVALID_STATE` (HTTP 409)".
    PRD §2.6: "Domain-specific business checks such as floor eligibility ... are
    evaluated within or after the state and referential checks".

    Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_periodic_dispatch
    """
    _, site, crew = fixtures.setup_account_site_crew(site_overrides={"floor_type": "CARPET"})
    job = fixtures.create_periodic_job(site["id"], job_type="STRIP_WAX", quoted_hours=2)
    validate_success(api.cancel_periodic_job(job["id"], AM), 200)  # terminal CANCELLED
    # both state (CANCELLED) and floor (CARPET ineligible) fail; state wins
    resp = api.dispatch_periodic_job(
        job["id"],
        {"crew_id": crew["id"], "service_date": "2026-06-12",
         "planned_start_min": 480, "planned_end_min": 600}, FS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_periodic_dispatch_invalid_state_not_floor_ineligible(api):
    """PRD §2.6: "they are evaluated in a fixed priority order so that the most
    fundamental failure is the one reported." PRD §2.6: "(7) ... yielding
    `ERR_INVALID_STATE` (HTTP 409)" before "floor eligibility ... evaluated within
    or after the state and referential checks".

    Design: Difficulty/priority_pair_validation_conflict/state_before_safety_on_periodic_dispatch
    """
    _, site, crew = fixtures.setup_account_site_crew(site_overrides={"floor_type": "CARPET"})
    job = fixtures.create_periodic_job(site["id"], job_type="STRIP_WAX", quoted_hours=2)
    validate_success(api.cancel_periodic_job(job["id"], AM), 200)
    resp = api.dispatch_periodic_job(
        job["id"],
        {"crew_id": crew["id"], "service_date": "2026-06-12",
         "planned_start_min": 480, "planned_end_min": 600}, FS)
    error_data = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert error_data["error_id"] != ApiErrorId.ERR_FLOOR_INELIGIBLE.value


# ===========================================================================
# Rule 6 instance A: shift_capacity_threshold_at_and_over_on_clock_out
# ===========================================================================
def _setup_crew_near_capacity():
    """Crew with 479 min already COMPLETED on 2026-06-16, plus a second visit B
    with an OPEN entry clocked in at 479. Returns (site, crew, teB_id)."""
    _, site, crew = fixtures.setup_account_site_crew(crew_overrides={"shift_capacity_min": 480})
    # Visit A: 479 min completed (00:00 -> 07:59)
    visit_a = fixtures.create_started_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=0, planned_end_min=479)
    fixtures.clock_full_entry(visit_a["id"], crew["id"], 0, 479)
    # Visit B adjacent at 479..600 (adjacency allowed), OPEN entry at 479
    visit_b = fixtures.create_started_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=479, planned_end_min=600)
    te_b = validate_success(api_client.create_time_entry(
        {"visit_id": visit_b["id"], "crew_id": crew["id"], "clock_in_min": 479}, FS), 201)
    return site, crew, te_b["id"]


def test_shift_capacity_exactly_at_cap_allowed(api):
    """PRD §3.4: "the crew's total clocked minutes for that crew across the visit's
    service local-day — counting this entry plus the crew's other already-
    `COMPLETED` entries on the same service date — must not exceed the crew's
    `shift_capacity_min`; exceeding it yields `ERR_SHIFT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/shift_capacity_threshold_at_and_over_on_clock_out
    """
    _site, _crew, te_b_id = _setup_crew_near_capacity()
    # 479 + (480-479) = 480 == cap -> allowed (does not exceed)
    resp = api.clock_out_time_entry(te_b_id, {"clock_out_min": 480}, FS)
    data = validate_success(resp, 200)
    assert data["status"] == "COMPLETED"
    assert data["clocked_min"] == 1


def test_shift_capacity_one_over_cap_rejected(api):
    """PRD §3.4: "the crew's total clocked minutes ... must not exceed the crew's
    `shift_capacity_min`; exceeding it yields `ERR_SHIFT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/shift_capacity_threshold_at_and_over_on_clock_out
    """
    _site, _crew, te_b_id = _setup_crew_near_capacity()
    # 479 + (481-479) = 481 > 480 -> rejected
    resp = api.clock_out_time_entry(te_b_id, {"clock_out_min": 481}, FS)
    validate_error(resp, ApiErrorId.ERR_SHIFT_CAPACITY_EXCEEDED.value)


# ===========================================================================
# Rule 6 instance B: crew_double_book_adjacency_allowed_on_visit_create
# (shares geometry with Rule 8 instance A; both translate the half-open rule)
# ===========================================================================
def test_visit_create_overlap_rejected_one_minute_before_boundary(api):
    """PRD §3.3: "the system rejects the new visit if it overlaps any existing
    non-terminal visit — one in `SCHEDULED` or `IN_PROGRESS` status — for the
    **same** crew on the **same** `service_date`. ... A collision yields
    `ERR_CREW_DOUBLE_BOOKED`."

    Design: Difficulty/boundary_precision_check/crew_double_book_adjacency_allowed_on_visit_create
    """
    _, site, crew = fixtures.setup_account_site_crew()
    fixtures.create_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=600, planned_end_min=660)
    # [659,720) overlaps [600,660) by one minute -> rejected
    resp = api.create_visit(
        {"site_id": site["id"], "crew_id": crew["id"], "service_date": "2026-06-16",
         "planned_start_min": 659, "planned_end_min": 720, "visit_kind": "ROUTINE"}, FS)
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)


def test_visit_create_adjacency_at_boundary_allowed(api):
    """PRD §3.3: "Adjacency is permitted: when one visit ends exactly at the minute
    another begins, that shared boundary is not an overlap."

    Design: Difficulty/boundary_precision_check/crew_double_book_adjacency_allowed_on_visit_create
    """
    _, site, crew = fixtures.setup_account_site_crew()
    fixtures.create_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=600, planned_end_min=660)
    # [660,720) is adjacent (end==start), allowed
    resp = api.create_visit(
        {"site_id": site["id"], "crew_id": crew["id"], "service_date": "2026-06-16",
         "planned_start_min": 660, "planned_end_min": 720, "visit_kind": "ROUTINE"}, FS)
    validate_success(resp, 201)


# ===========================================================================
# Rule 7 instance A: visit_start_blocked_by_inactive_crew
# ===========================================================================
def test_visit_start_blocked_by_inactive_crew(api):
    """PRD §3.3: "starting requires that the visit's `crew_id` crew is `AVAILABLE`
    (otherwise `ERR_CREW_INACTIVE`) and that the site is `ACTIVE` (otherwise
    `ERR_SITE_ARCHIVED`)."

    Design: Difficulty/cross_entity_state_dependency/visit_start_blocked_by_inactive_crew
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_visit(site["id"], crew["id"])
    validate_success(api.deactivate_crew(crew["id"], FS), 200)
    resp = api.start_visit(visit["id"], FS)
    validate_error(resp, ApiErrorId.ERR_CREW_INACTIVE.value)


def test_visit_start_blocked_by_inactive_crew_leaves_visit_scheduled(api):
    """PRD §3.2: "an inactive crew member can neither be assigned to a route nor
    clocked onto a visit, and any operation that references an inactive crew is
    refused with `ERR_CREW_INACTIVE`." PRD §3.3: "starting requires that the
    visit's `crew_id` crew is `AVAILABLE` (otherwise `ERR_CREW_INACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/visit_start_blocked_by_inactive_crew
    """
    _, site, crew = fixtures.setup_account_site_crew()
    visit = fixtures.create_visit(site["id"], crew["id"])
    validate_success(api.deactivate_crew(crew["id"], FS), 200)
    validate_error(api.start_visit(visit["id"], FS), ApiErrorId.ERR_CREW_INACTIVE.value)
    after = validate_success(api.get_visit(visit["id"], FS), 200)
    assert after["status"] == "SCHEDULED"


# ===========================================================================
# Rule 7 instance B: contract_activate_blocked_by_suspended_account
# ===========================================================================
def test_contract_activate_blocked_by_suspended_account(api):
    """PRD §3.9: "activation requires the site to be `ACTIVE` (otherwise
    `ERR_SITE_ARCHIVED`) and the owning account to be `ACTIVE` (otherwise
    `ERR_ACCOUNT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/contract_activate_blocked_by_suspended_account
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"])
    contract = fixtures.create_draft_contract(site["id"])
    validate_success(api.suspend_account(acct["id"], AM), 200)
    resp = api.activate_contract(contract["id"], AM)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_contract_activate_blocked_leaves_contract_draft(api):
    """PRD §3.1: "a suspended (or `CLOSED`) account is no longer `ACTIVE`, and any
    operation that requires the owning account to be `ACTIVE` will be refused with
    `ERR_ACCOUNT_NOT_ACTIVE`." PRD §3.9: "activation requires ... the owning
    account to be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/contract_activate_blocked_by_suspended_account
    """
    acct = fixtures.create_account()
    site = fixtures.create_site(acct["id"])
    contract = fixtures.create_draft_contract(site["id"])
    validate_success(api.suspend_account(acct["id"], AM), 200)
    validate_error(api.activate_contract(contract["id"], AM), ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)
    after = validate_success(api.get_contract(contract["id"], AM), 200)
    assert after["status"] == "DRAFT"


# ===========================================================================
# Rule 8 instance A: visit_crew_overlap_half_open_adjacency_allowed
# ===========================================================================
def test_visit_overlap_half_open_rejected(api):
    """PRD §3.3: "Treating the planned span as the half-open interval from
    `planned_start_min` up to but not including `planned_end_min`, the system
    rejects the new visit if it overlaps any existing non-terminal visit ... for
    the **same** crew on the **same** `service_date`."

    Design: Difficulty/resource_temporal_overlap/visit_crew_overlap_half_open_adjacency_allowed
    """
    _, site, crew = fixtures.setup_account_site_crew()
    fixtures.create_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=600, planned_end_min=660)
    fixtures.create_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=660, planned_end_min=720)  # adjacent, allowed
    # [630,690) overlaps [600,660) -> rejected
    resp = api.create_visit(
        {"site_id": site["id"], "crew_id": crew["id"], "service_date": "2026-06-16",
         "planned_start_min": 630, "planned_end_min": 690, "visit_kind": "ROUTINE"}, FS)
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)


def test_visit_adjacency_allowed_distinct_from_overlap(api):
    """PRD §3.3: "Adjacency is permitted: when one visit ends exactly at the minute
    another begins, that shared boundary is not an overlap."

    Design: Difficulty/resource_temporal_overlap/visit_crew_overlap_half_open_adjacency_allowed
    """
    _, site, crew = fixtures.setup_account_site_crew()
    fixtures.create_visit(
        site["id"], crew["id"], service_date="2026-06-16",
        planned_start_min=600, planned_end_min=660)
    # [660,720) adjacency -> 201
    resp = api.create_visit(
        {"site_id": site["id"], "crew_id": crew["id"], "service_date": "2026-06-16",
         "planned_start_min": 660, "planned_end_min": 720, "visit_kind": "ROUTINE"}, FS)
    validate_success(resp, 201)


# ===========================================================================
# Rule 8 instance B: schedule_window_closed_interval_touching_conflict
# ===========================================================================
def test_schedule_window_touching_boundary_is_conflict(api):
    """PRD §3.2: "The conflict test uses closed-interval semantics: the windows
    `[window_start_min, window_end_min]` are compared inclusively, so two windows
    that merely touch at a shared boundary minute are treated as a conflict. A
    conflict yields `ERR_SCHEDULE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/schedule_window_closed_interval_touching_conflict
    """
    _, site, crew = fixtures.setup_account_site_crew()
    validate_success(api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 600,
         "window_end_min": 660, "assigned_crew_id": crew["id"]}, FS), 201)
    # [660,720] touches [600,660] at 660 -> closed-interval conflict
    resp = api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 660,
         "window_end_min": 720, "assigned_crew_id": crew["id"]}, FS)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_CONFLICT.value)


def test_schedule_window_nonoverlapping_distinct_weekday_allowed(api):
    """PRD §3.2: "When a new schedule is created, the system rejects any window
    that overlaps another `ACTIVE` schedule for the **same** crew on the **same**
    weekday." A different weekday is not a conflict.

    Design: Difficulty/resource_temporal_overlap/schedule_window_closed_interval_touching_conflict
    """
    _, site, crew = fixtures.setup_account_site_crew()
    validate_success(api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 600,
         "window_end_min": 660, "assigned_crew_id": crew["id"]}, FS), 201)
    # same touching window but on weekday 1 -> different weekday, allowed
    resp = api.create_schedule(
        {"site_id": site["id"], "weekday": 1, "window_start_min": 660,
         "window_end_min": 720, "assigned_crew_id": crew["id"]}, FS)
    validate_success(resp, 201)


# ===========================================================================
# Rule 9 instance A: invoice_line_sum_equals_period_total_across_close_reopen
# ===========================================================================
def test_invoice_lines_sum_equals_total_while_closed(api):
    """PRD §3.9: "emits the immutable invoice-line ledger for the period — a `BASE`
    line, one `PERIODIC` line for the summed captured periodic charges, one
    `CALLBACK_CREDIT` line, and one `HOLDBACK` line, each carrying a signed
    `amount_cents` (positive for charges, negative for credits and holdback)".

    Design: Difficulty/compensating_invariant/invoice_line_sum_equals_period_total_across_close_reopen
    """
    bundle = fixtures.setup_billing_scenario(
        crew=False, contract_overrides={"monthly_base_cents": 300000})
    closed = fixtures.close_period(bundle["period"]["id"], bundle["account"]["id"])
    assert closed["total_cents"] == 300000
    data, _meta = validate_paginated(api.list_invoice_lines(bundle["period"]["id"], AM))
    line_sum = sum(ln["amount_cents"] for ln in data)
    assert line_sum == closed["total_cents"] == 300000


def test_invoice_lines_deleted_after_reopen(api):
    """PRD §3.9: "Reopening deletes the invoice lines previously emitted for the
    period as a compensating action, reverts `total_cents` to a provisional
    recompute, sets the period's `status` to `REOPENED`".

    Design: Difficulty/compensating_invariant/invoice_line_sum_equals_period_total_across_close_reopen
    """
    bundle = fixtures.setup_billing_scenario(
        crew=False, contract_overrides={"monthly_base_cents": 300000})
    fixtures.close_period(bundle["period"]["id"], bundle["account"]["id"])
    fixtures.reopen_period(bundle["period"]["id"], bundle["account"]["id"])
    data, meta = validate_paginated(api.list_invoice_lines(bundle["period"]["id"], AM))
    assert meta["total_count"] == 0
    assert data == []


# ===========================================================================
# Rule 9 instance B: account_version_monotonic_invariant_close_reopen_close
# ===========================================================================
def test_account_version_increments_one_per_period_act(api):
    """PRD §3.9: "On a successful close, the system ... increments the owning
    account's `version` by 1." PRD §3.9: "Reopening ... increments the account's
    `version` by 1." PRD §3.9: "A `REOPENED` period can be closed again ... once
    more increments the account's `version` by 1."

    Design: Difficulty/compensating_invariant/account_version_monotonic_invariant_close_reopen_close
    """
    bundle = fixtures.setup_billing_scenario(crew=False)
    period, acct = bundle["period"], bundle["account"]
    v_open = fixtures.get_account_version(acct["id"])
    fixtures.close_period(period["id"], acct["id"])
    v_after_close = fixtures.get_account_version(acct["id"])
    assert v_after_close == v_open + 1
    fixtures.reopen_period(period["id"], acct["id"])
    v_after_reopen = fixtures.get_account_version(acct["id"])
    assert v_after_reopen == v_open + 2
    fixtures.close_period(period["id"], acct["id"])
    v_final = fixtures.get_account_version(acct["id"])
    assert v_final == v_open + 3


def test_stale_account_version_rejects_close(api):
    """PRD §2.8: "The server compares it to the owning Account's current `version`.
    If they do not match — because some other close, reopen, or re-close of any
    period under that account has advanced the account's `version` since the
    client last read it — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and no state change or ledger mutation occurs."

    Design: Difficulty/compensating_invariant/account_version_monotonic_invariant_close_reopen_close
    """
    bundle = fixtures.setup_billing_scenario(crew=False)
    period, acct = bundle["period"], bundle["account"]
    v_open = fixtures.get_account_version(acct["id"])
    # close advances version to v_open+1
    fixtures.close_period(period["id"], acct["id"])
    # reopen using the now-stale v_open -> rejected
    resp = api.reopen_billing_period(period["id"], {"expected_account_version": v_open}, AM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
