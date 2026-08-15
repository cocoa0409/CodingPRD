"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.

Unless a fixture sets the logical clock explicitly, the clock sits at its
startup default of 2026-08-01T00:00:00Z (PRD §2.5), which is comfortably
before every swap cutoff and credentialing deadline used by the suite.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client
from .constants import CREDENTIALING_ITEMS
from .factories import (
    activate_backup_payload,
    create_assignment_payload,
    create_physician_payload,
    create_program_payload,
    create_requisition_payload,
    create_swap_payload,
    create_window_payload,
)
from .test_users import TEST_USERS, make_physician_headers

ADMIN = TEST_USERS["admin_headers"]
CHIEF = TEST_USERS["chief_headers"]
CRED = TEST_USERS["cred_officer_headers"]


# ─── Clock (PRD §2.5) ────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Set the server-side logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: program lifecycle (PRD §3.1) ────────────────────────────

def create_draft_program(**overrides) -> dict:
    """Create a DRAFT call program. Returns the program data."""
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN)
    )


def generate_program(program_id) -> dict:
    """DRAFT -> GENERATED: create slots and run rotation auto-assignment."""
    return get_success_data(api_client.generate_program(program_id, ADMIN))


def publish_program(program_id) -> dict:
    """GENERATED -> PUBLISHED."""
    return get_success_data(api_client.publish_program(program_id, ADMIN))


def create_generated_program(**overrides) -> dict:
    """Program created and generated (slots + auto-assignment run)."""
    program = create_draft_program(**overrides)
    return generate_program(program["id"])


def create_published_program(**overrides) -> dict:
    """Program created, generated and published. Returns the PUBLISHED program."""
    program = create_draft_program(**overrides)
    generate_program(program["id"])
    return publish_program(program["id"])


# ─── Tier 1: physician registry (PRD §3.2) ───────────────────────────

def create_physician(**overrides) -> dict:
    """Register a physician (ACTIVE). Returns the physician data."""
    return get_success_data(
        api_client.create_physician(create_physician_payload(**overrides), ADMIN)
    )


def create_staff_physician(name="Dr Alvarez", **overrides) -> dict:
    return create_physician(full_name=name, employment_type="STAFF", **overrides)


def create_locum_physician(name="Dr Locum", **overrides) -> dict:
    return create_physician(full_name=name, employment_type="LOCUM", **overrides)


# ─── Tier 2: slot and gap lookups ────────────────────────────────────

def list_slots(program_id=None, **filters):
    params = dict(filters)
    if program_id is not None:
        params["program_id"] = program_id
    data, _meta = validate_paginated(api_client.list_slots(ADMIN, params=params))
    return data


def get_slot_for_date(program_id, date, call_type=None, index=0) -> dict:
    """Fetch the index-th slot of a date. Listing order is pinned by the PRD:
    date ASC, then call_type ASC (BACKUP before PRIMARY), then position_index."""
    filters = {"date": date}
    if call_type is not None:
        filters["call_type"] = call_type
    slots = list_slots(program_id, **filters)
    assert len(slots) > index, (
        f"Expected slot index {index} for program {program_id} date {date} "
        f"call_type {call_type}; got {len(slots)} slot(s)"
    )
    return slots[index]


def list_gaps(program_id=None, **filters):
    params = dict(filters)
    if program_id is not None:
        params["program_id"] = program_id
    data, _meta = validate_paginated(api_client.list_gaps(ADMIN, params=params))
    return data


def get_open_gap(program_id, index=0) -> dict:
    gaps = list_gaps(program_id, status="OPEN")
    assert len(gaps) > index, f"Expected an OPEN gap for program {program_id}"
    return gaps[index]


# ─── Tier 2: assignments (PRD §3.3) ──────────────────────────────────

def assign_staff(slot_id, physician_id) -> dict:
    """Manual assignment of a STAFF physician to an OPEN slot (origin MANUAL)."""
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(slot_id, physician_id), ADMIN
        )
    )


def serve_assignment(assignment_id) -> dict:
    """mark-served; caller is responsible for having advanced the clock past
    the slot's window_end."""
    return get_success_data(api_client.mark_served(assignment_id, ADMIN))


def cancel_assignment(assignment_id) -> dict:
    return get_success_data(api_client.cancel_assignment(assignment_id, ADMIN))


def activate_backup(assignment_id, physician_id=None, reason="PRIMARY_NO_SHOW") -> dict:
    """activate-backup; as the assignee Physician when physician_id is given,
    otherwise as SchedulerAdmin."""
    headers = make_physician_headers(physician_id) if physician_id else ADMIN
    return get_success_data(
        api_client.activate_backup(assignment_id, activate_backup_payload(reason), headers)
    )


def get_pay_entry_for_assignment(assignment_id) -> dict:
    data, _meta = validate_paginated(
        api_client.list_pay_entries(ADMIN, params={"assignment_id": assignment_id})
    )
    assert len(data) == 1, f"Expected exactly one pay entry for {assignment_id}"
    return data[0]


def list_assignments(**filters):
    data, _meta = validate_paginated(api_client.list_assignments(ADMIN, params=filters))
    return data


# ─── Tier 3: published program with one staff assignment ─────────────

def setup_published_with_assignment(
    date="2026-09-08",
    call_type="PRIMARY",
    weekday_primary_required=1,
    weekday_backup_required=0,
    physician_overrides=None,
    **program_overrides,
):
    """PUBLISHED single-day program + one STAFF cardiologist manually assigned
    to the day's slot. Returns (program, physician, slot, assignment).

    Generation runs before the physician exists, so the slot starts OPEN with
    a GENERATION_SHORTFALL gap; the manual backfill resolves it.
    """
    program_overrides.setdefault("period_start", date)
    program_overrides.setdefault("period_end", date)
    program_overrides["weekday_primary_required"] = weekday_primary_required
    program_overrides["weekday_backup_required"] = weekday_backup_required
    program = create_published_program(**program_overrides)
    physician = create_staff_physician(**(physician_overrides or {}))
    slot = get_slot_for_date(program["id"], date, call_type=call_type)
    assignment = assign_staff(slot["id"], physician["id"])
    return program, physician, slot, assignment


# ─── Tier 4: swap marketplace (PRD §3.4) ─────────────────────────────

def post_swap(assignment_id, offerer_id) -> dict:
    """Offer a SCHEDULED assignment; the caller must own it."""
    return get_success_data(
        api_client.create_swap(
            create_swap_payload(assignment_id), make_physician_headers(offerer_id)
        )
    )


def claim_swap(swap_id, claimant_id) -> dict:
    return get_success_data(
        api_client.claim_swap(swap_id, make_physician_headers(claimant_id))
    )


def setup_posted_swap(date="2026-09-08", **program_overrides):
    """PUBLISHED single-day program, offerer assigned, swap POSTED.
    Returns dict(program, offerer, claimant, slot, assignment, swap)."""
    program, offerer, slot, assignment = setup_published_with_assignment(
        date=date, **program_overrides
    )
    claimant = create_staff_physician("Dr Becker")
    swap = post_swap(assignment["id"], offerer["id"])
    return {
        "program": program,
        "offerer": offerer,
        "claimant": claimant,
        "slot": slot,
        "assignment": assignment,
        "swap": swap,
    }


def setup_claimed_swap(date="2026-09-08", **program_overrides):
    """Posted swap + claimant claim. The default startup clock is well before
    the 48-hour swap cutoff for the dates used by this suite."""
    ctx = setup_posted_swap(date=date, **program_overrides)
    claim_swap(ctx["swap"]["id"], ctx["claimant"]["id"])
    ctx["swap"] = get_success_data(api_client.get_swap(ctx["swap"]["id"], ADMIN))
    return ctx


def setup_approved_swap(date="2026-09-08", **program_overrides):
    """Claimed swap + ChiefOfStaff approval."""
    ctx = setup_claimed_swap(date=date, **program_overrides)
    get_success_data(api_client.approve_swap(ctx["swap"]["id"], CHIEF))
    ctx["swap"] = get_success_data(api_client.get_swap(ctx["swap"]["id"], ADMIN))
    return ctx


# ─── Tier 5: coverage gap -> locum requisition -> credentialing ──────

def setup_shortfall_program(date="2026-09-08", **program_overrides):
    """PUBLISHED single-day program generated with zero physicians: the day's
    slot stays OPEN with a GENERATION_SHORTFALL gap. Returns (program, slot, gap)."""
    program_overrides.setdefault("period_start", date)
    program_overrides.setdefault("period_end", date)
    program = create_published_program(**program_overrides)
    slot = get_slot_for_date(program["id"], date)
    gap = get_open_gap(program["id"])
    return program, slot, gap


def setup_open_requisition(date="2026-09-08", **program_overrides):
    """Shortfall program + an OPEN locum requisition against the gap.
    The default startup clock keeps credentialing feasible (clear_by is the
    slot window_start minus the 120-hour lead)."""
    program, slot, gap = setup_shortfall_program(date=date, **program_overrides)
    requisition = get_success_data(
        api_client.create_requisition(create_requisition_payload(gap["id"]), ADMIN)
    )
    return program, slot, gap, requisition


def setup_sourced_requisition(date="2026-09-08", locum_name="Dr Locum", **program_overrides):
    """Open requisition + LOCUM candidate proposed (SOURCED).
    Returns (program, slot, gap, requisition, locum)."""
    program, slot, gap, requisition = setup_open_requisition(date=date, **program_overrides)
    locum = create_locum_physician(locum_name)
    requisition = get_success_data(
        api_client.propose_candidate(requisition["id"], locum["id"], ADMIN)
    )
    return program, slot, gap, requisition, locum


def setup_credentialing_case(date="2026-09-08", locum_name="Dr Locum", **program_overrides):
    """Requisition in CREDENTIALING with an INITIATED case.
    Returns (program, slot, gap, requisition, locum, case)."""
    program, slot, gap, requisition, locum = setup_sourced_requisition(
        date=date, locum_name=locum_name, **program_overrides
    )
    requisition = get_success_data(api_client.begin_credentialing(requisition["id"], CRED))
    case = get_case_for_requisition(requisition["id"])
    return program, slot, gap, requisition, locum, case


def get_case_for_requisition(requisition_id, index=0) -> dict:
    data, _meta = validate_paginated(
        api_client.list_cases(CRED, params={"requisition_id": requisition_id})
    )
    assert len(data) > index, (
        f"Expected case index {index} for requisition {requisition_id}; got {len(data)}"
    )
    return data[index]


def complete_item(case_id, item) -> dict:
    return get_success_data(api_client.complete_item(case_id, item, CRED))


def setup_filled_requisition(date="2026-09-08", **program_overrides):
    """Drive a requisition all the way to FILLED: all five checklist items
    completed, case CLEARED, auto-fill cascade fired.
    Returns (program, slot, gap, requisition, locum, case)."""
    program, slot, gap, requisition, locum, case = setup_credentialing_case(
        date=date, **program_overrides
    )
    for item in CREDENTIALING_ITEMS:
        case = complete_item(case["id"], item)
    requisition = get_success_data(api_client.get_requisition(requisition["id"], ADMIN))
    return program, slot, gap, requisition, locum, case


# ─── Tier 5: unavailability windows (PRD §3.2) ───────────────────────

def create_window(physician_id, as_admin=False, **overrides) -> dict:
    """Request an unavailability window (REQUESTED). As the owning Physician
    by default; pass as_admin=True for a SchedulerAdmin-created window."""
    headers = ADMIN if as_admin else make_physician_headers(physician_id)
    return get_success_data(
        api_client.create_window(create_window_payload(physician_id, **overrides), headers)
    )


def approve_window(window_id) -> dict:
    return get_success_data(api_client.approve_window(window_id, ADMIN))


def create_approved_window(physician_id, **overrides) -> dict:
    window = create_window(physician_id, **overrides)
    return approve_window(window["id"])


# ─── Reports ─────────────────────────────────────────────────────────

def get_fairness_report(program_id) -> dict:
    return validate_success(api_client.get_fairness_report(program_id, ADMIN))


def get_coverage_report(program_id) -> dict:
    return validate_success(api_client.get_coverage_report(program_id, ADMIN))


def get_program(program_id) -> dict:
    return validate_success(api_client.get_program(program_id, ADMIN))


def fairness_entry_for(report: dict, physician_id) -> dict:
    """Locate a physician's per-physician entry in the fairness report.

    The PRD pins the report's top-level fields and that each entry corresponds
    to one population physician with their prospective and actual point
    values; the entry's physician reference is matched by value so the test
    does not depend on key naming.
    """
    for entry in report["entries"]:
        if physician_id in (str(v) for v in entry.values()):
            return entry
    raise AssertionError(
        f"No fairness-report entry found for physician {physician_id}: {report['entries']!r}"
    )


def numeric_values(entry: dict) -> list:
    """Numeric values of a report entry (point totals), excluding booleans."""
    return [v for v in entry.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
