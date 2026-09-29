"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only PRD-declared endpoints. Helpers use the
lenient `get_success_data()` validator so a broken precondition surfaces as a
setup failure rather than as a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_STARTUP_UTC,
    CONTRACT_SENDER_USER_ID,
    CONTRACT_SIGNER_USER_ID,
    CONTROLLER_APPROVER_USER_ID,
)
from .factories import (
    create_manifest_entry_payload,
    create_permit_payload,
    create_program_element_payload,
    create_program_payload,
    create_settlement_payment_payload,
    create_staff_assignment_payload,
    create_staff_member_payload,
    create_supplier_contract_payload,
    create_supplier_payload,
    create_transport_segment_payload,
    create_venue_payload,
)
from .test_users import (
    TEST_USERS,
    make_controller_headers,
    make_operations_coordinator_headers,
    make_supplier_headers,
    make_supplier_manager_headers,
)

PD = TEST_USERS["program_director_headers"]
OC = TEST_USERS["operations_coordinator_headers"]
SM = TEST_USERS["supplier_manager_headers"]
CTRL = TEST_USERS["controller_headers"]
PO = TEST_USERS["permit_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-step primitives
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, headers=None) -> dict:
    """Move the logical clock. Returns the echoed clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or PD))


def reset_clock() -> dict:
    """Return the logical clock to the value it holds at start-up."""
    return set_clock(CLOCK_STARTUP_UTC)


def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), PD))


def create_supplier(**overrides) -> dict:
    return get_success_data(
        api_client.create_supplier(create_supplier_payload(**overrides), SM)
    )


def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), PD)
    )


def read_program(program_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_program(program_id, headers or PD))


def create_staff_member(**overrides) -> dict:
    return get_success_data(
        api_client.create_staff_member(create_staff_member_payload(**overrides), PD)
    )


def create_transport_segment(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_transport_segment(
            create_transport_segment_payload(program_id, **overrides), OC
        )
    )


def manifest_guest(segment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_manifest_entry(
            create_manifest_entry_payload(segment_id, **overrides), OC
        )
    )


def create_permit(element_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_permit(create_permit_payload(element_id, **overrides), PO)
    )


def submit_permit(permit_id: str) -> dict:
    return get_success_data(api_client.submit_permit(permit_id, PO))


def record_permit_decision(permit_id: str, decision: str, conditions_note=None) -> dict:
    payload = {"decision": decision}
    if conditions_note is not None:
        payload["conditions_note"] = conditions_note
    return get_success_data(api_client.record_permit_decision(permit_id, payload, PO))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------
def add_element(program_id: str, supplier_id: str, **overrides) -> dict:
    """Add one element, re-reading the programme so the version guard is current."""
    program = read_program(program_id)
    payload = create_program_element_payload(
        program_id, supplier_id, program["version"], **overrides
    )
    return get_success_data(api_client.create_program_element(payload, PD))


def draft_contract(program_id: str, supplier_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_supplier_contract(
            create_supplier_contract_payload(program_id, supplier_id, **overrides), SM
        )
    )


def create_sent_contract(program_id: str, supplier_id: str, **overrides) -> dict:
    """Draft a contract and send it, leaving it in SENT."""
    contract = draft_contract(program_id, supplier_id, **overrides)
    get_success_data(
        api_client.send_supplier_contract(
            contract["id"], make_supplier_manager_headers(CONTRACT_SENDER_USER_ID)
        )
    )
    return get_success_data(api_client.get_supplier_contract(contract["id"], SM))


def create_active_contract(program_id: str, supplier_id: str, **overrides) -> dict:
    """Draft, send and countersign a contract, leaving it ACTIVE.

    The sender and the countersigner are two different operator identifiers so
    the segregation-of-duties comparison passes.
    """
    contract = create_sent_contract(program_id, supplier_id, **overrides)
    return get_success_data(
        api_client.countersign_supplier_contract(
            contract["id"], make_supplier_manager_headers(CONTRACT_SIGNER_USER_ID)
        )
    )


def counter_contract(contract_id: str, supplier_id: str, countered_value_cents: int) -> dict:
    return get_success_data(
        api_client.counter_supplier_contract(
            contract_id,
            {"countered_value_cents": countered_value_cents},
            make_supplier_headers(supplier_id),
        )
    )


def resend_contract(contract_id: str) -> dict:
    return get_success_data(
        api_client.send_supplier_contract(
            contract_id, make_supplier_manager_headers(CONTRACT_SENDER_USER_ID)
        )
    )


def lock_design(program_id: str) -> dict:
    return get_success_data(api_client.lock_program_design(program_id, PD))


def confirm_program(program_id: str) -> dict:
    return get_success_data(api_client.confirm_program(program_id, PD))


def start_execution(program_id: str, clock: str = "2026-09-10T08:00:00Z") -> dict:
    """Move the clock into the programme window and open on-site execution."""
    if clock:
        set_clock(clock)
    return get_success_data(api_client.start_program_execution(program_id, OC))


def mark_ready(element_id: str) -> dict:
    return get_success_data(api_client.mark_element_ready(element_id, OC))


def deliver(element_id: str, actual_headcount: int, clock: str = None) -> dict:
    if clock:
        set_clock(clock)
    return get_success_data(
        api_client.deliver_element(element_id, {"actual_headcount": actual_headcount}, OC)
    )


def propose_assignment(staff_id: str, program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_assignment(
            create_staff_assignment_payload(staff_id, program_id, **overrides), PD
        )
    )


def confirm_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.confirm_staff_assignment(assignment_id, PD))


def staff_check_in(assignment_id: str, staff_id: str, clock: str = None) -> dict:
    """On-site check-in, threaded with the acting staff member's own identity."""
    if clock:
        set_clock(clock)
    return get_success_data(
        api_client.check_in_staff_assignment(
            assignment_id, make_operations_coordinator_headers(staff_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------
def setup_program_with_element(
    program_overrides=None,
    element_overrides=None,
    venue_overrides=None,
    supplier_overrides=None,
    clock: str = CLOCK_STARTUP_UTC,
    with_venue: bool = True,
):
    """Clock pinned, one venue, one APPROVED supplier, one DRAFT programme with
    one PLANNED element. Returns a dict with `venue`, `supplier`, `program` and
    `element`.
    """
    if clock:
        set_clock(clock)
    venue = create_venue(**(venue_overrides or {})) if with_venue else None
    supplier = create_supplier(**(supplier_overrides or {}))
    program = create_program(**(program_overrides or {}))
    element_kwargs = dict(element_overrides or {})
    if with_venue and "venue_id" not in element_kwargs:
        element_kwargs["venue_id"] = venue["id"]
    element = add_element(program["id"], supplier["id"], **element_kwargs)
    return {
        "venue": venue,
        "supplier": supplier,
        "program": program,
        "element": element,
    }


def setup_program_with_contracted_element(
    program_overrides=None,
    element_overrides=None,
    venue_overrides=None,
    supplier_overrides=None,
    contract_overrides=None,
    clock: str = CLOCK_STARTUP_UTC,
    with_venue: bool = True,
):
    """As `setup_program_with_element`, plus an ACTIVE supplier contract for the
    (programme, supplier) pair. Returns the same dict with `contract` added.
    """
    ctx = setup_program_with_element(
        program_overrides=program_overrides,
        element_overrides=element_overrides,
        venue_overrides=venue_overrides,
        supplier_overrides=supplier_overrides,
        clock=clock,
        with_venue=with_venue,
    )
    ctx["contract"] = create_active_contract(
        ctx["program"]["id"], ctx["supplier"]["id"], **(contract_overrides or {})
    )
    return ctx


def setup_program_with_segment(
    program_overrides=None, segment_overrides=None, clock: str = CLOCK_STARTUP_UTC
):
    """One programme plus one SCHEDULED transport segment on it."""
    if clock:
        set_clock(clock)
    program = create_program(**(program_overrides or {}))
    segment = create_transport_segment(program["id"], **(segment_overrides or {}))
    return {"program": program, "segment": segment}


def setup_locked_program_with_segment(
    program_overrides=None,
    segment_overrides=None,
    supplier_overrides=None,
    element_overrides=None,
    clock: str = CLOCK_STARTUP_UTC,
):
    """A DESIGN_LOCKED programme with one transfer-block element and one
    SCHEDULED transport segment.

    Shift confirmation requires the programme to have left `DRAFT`, and the
    design lock requires the programme to own at least one element, so the
    transfer block exists purely to make the lock legal. Returns `supplier`,
    `program`, `element` and `segment`.
    """
    if clock:
        set_clock(clock)
    supplier = create_supplier(**(supplier_overrides or {}))
    program = create_program(**(program_overrides or {}))
    element_kwargs = {
        "element_type": "TRANSFER_BLOCK",
        "title": "Airport Transfer Block",
        "starts_at": "2026-09-13T09:00:00Z",
        "ends_at": "2026-09-13T10:00:00Z",
        "planned_headcount": 10,
        "guaranteed_headcount": 10,
        "per_person_cost_cents": 1_000,
    }
    element_kwargs.update(element_overrides or {})
    element = add_element(program["id"], supplier["id"], **element_kwargs)
    segment = create_transport_segment(program["id"], **(segment_overrides or {}))
    program = lock_design(program["id"])
    return {
        "supplier": supplier,
        "program": program,
        "element": element,
        "segment": segment,
    }


def setup_confirmed_staff_shift(
    staff_overrides=None,
    assignment_overrides=None,
    program_overrides=None,
    segment_overrides=None,
    clock: str = CLOCK_STARTUP_UTC,
):
    """A DESIGN_LOCKED programme with one segment, one ACTIVE staff member and
    one CONFIRMED shift against that segment. Returns `program`, `segment`,
    `staff`, `assignment`.
    """
    ctx = setup_locked_program_with_segment(
        program_overrides=program_overrides,
        segment_overrides=segment_overrides,
        clock=clock,
    )
    staff = create_staff_member(**(staff_overrides or {}))
    assignment_kwargs = {
        "target_type": "SEGMENT",
        "segment_id": ctx["segment"]["id"],
        "role_type": staff["role_type"],
    }
    assignment_kwargs.update(assignment_overrides or {})
    assignment = propose_assignment(staff["id"], ctx["program"]["id"], **assignment_kwargs)
    confirmed = confirm_assignment(assignment["id"])
    ctx.update({"staff": staff, "assignment": confirmed})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------
def advance_to_in_execution(program_id: str, clock: str = "2026-09-10T08:00:00Z") -> dict:
    """DRAFT -> DESIGN_LOCKED -> CONFIRMED -> IN_EXECUTION."""
    lock_design(program_id)
    confirm_program(program_id)
    return start_execution(program_id, clock=clock)


def setup_delivered_single_element_program(
    actual_headcount: int = 40,
    deliver_clock: str = "2026-09-11T13:30:00Z",
    program_overrides=None,
    element_overrides=None,
    venue_overrides=None,
    supplier_overrides=None,
    contract_overrides=None,
    execution_clock: str = "2026-09-10T08:00:00Z",
):
    """Full run to a COMPLETED programme: contracted element, programme locked,
    confirmed and in execution, element READY then DELIVERED, and the programme
    completed by the bubble-up. Returns the setup dict plus `program` re-read.
    """
    ctx = setup_program_with_contracted_element(
        program_overrides=program_overrides,
        element_overrides=element_overrides,
        venue_overrides=venue_overrides,
        supplier_overrides=supplier_overrides,
        contract_overrides=contract_overrides,
    )
    advance_to_in_execution(ctx["program"]["id"], clock=execution_clock)
    mark_ready(ctx["element"]["id"])
    ctx["element"] = deliver(ctx["element"]["id"], actual_headcount, clock=deliver_clock)
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def open_reconciliation(program_id: str) -> list:
    """Open reconciliation and return the materialised lines in listing order."""
    get_success_data(api_client.reconcile_program(program_id, PD))
    listing = get_success_data(
        api_client.list_reconciliation_lines(PD, params={"program_id": program_id, "limit": 100})
    )
    return listing


def patch_line(line_id: str, **payload) -> dict:
    return get_success_data(api_client.patch_reconciliation_line(line_id, payload, PD))


def approve_line(line_id: str) -> dict:
    return get_success_data(api_client.approve_reconciliation_line(line_id, PD))


def issue_invoice(program_id: str, user_id: str = CONTROLLER_APPROVER_USER_ID) -> dict:
    return get_success_data(
        api_client.issue_program_invoice(program_id, make_controller_headers(user_id))
    )


def setup_invoiced_program(
    actual_headcount: int = 40,
    variance_reason: str = None,
    deliver_clock: str = "2026-09-11T13:30:00Z",
    program_overrides=None,
    element_overrides=None,
    venue_overrides=None,
    supplier_overrides=None,
    contract_overrides=None,
):
    """Run one element all the way to an issued client invoice.

    Returns the setup dict plus `lines` (the reconciliation lines) and a freshly
    read `program`.
    """
    ctx = setup_delivered_single_element_program(
        actual_headcount=actual_headcount,
        deliver_clock=deliver_clock,
        program_overrides=program_overrides,
        element_overrides=element_overrides,
        venue_overrides=venue_overrides,
        supplier_overrides=supplier_overrides,
        contract_overrides=contract_overrides,
    )
    lines = open_reconciliation(ctx["program"]["id"])
    for line in lines:
        if variance_reason:
            patch_line(line["id"], variance_reason=variance_reason)
        approve_line(line["id"])
    ctx["program"] = issue_invoice(ctx["program"]["id"])
    ctx["lines"] = [
        get_success_data(api_client.get_reconciliation_line(line["id"], PD))
        for line in lines
    ]
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------
def setup_program_with_seated_manifest(
    seat_counts,
    seat_capacity: int = 20,
    program_overrides=None,
    segment_overrides=None,
    clock: str = CLOCK_STARTUP_UTC,
):
    """One SCHEDULED segment carrying one manifest entry per element of
    `seat_counts`, so the segment's booked seat count reaches their sum.
    Returns `program`, `segment`, `entries`.
    """
    seg_overrides = {"seat_capacity": seat_capacity}
    seg_overrides.update(segment_overrides or {})
    ctx = setup_program_with_segment(
        program_overrides=program_overrides,
        segment_overrides=seg_overrides,
        clock=clock,
    )
    entries = []
    for index, seats in enumerate(seat_counts, start=1):
        entries.append(
            manifest_guest(
                ctx["segment"]["id"],
                guest_ref=f"G-{100 + index}",
                guest_name=f"Party {index}",
                seat_count=seats,
            )
        )
    ctx["entries"] = entries
    ctx["segment"] = get_success_data(
        api_client.get_transport_segment(ctx["segment"]["id"], OC)
    )
    return ctx


def setup_multi_element_program(
    element_specs,
    program_overrides=None,
    venue_overrides=None,
    supplier_overrides=None,
    contract_overrides=None,
    clock: str = CLOCK_STARTUP_UTC,
):
    """A DRAFT programme carrying one element per entry of `element_specs`
    (each a kwargs dict for the element payload), plus an ACTIVE contract.
    Returns `venue`, `supplier`, `program`, `elements`, `contract`.
    """
    if clock:
        set_clock(clock)
    venue = create_venue(**(venue_overrides or {}))
    supplier = create_supplier(**(supplier_overrides or {}))
    program = create_program(**(program_overrides or {}))
    elements = []
    for spec in element_specs:
        kwargs = dict(spec)
        kwargs.setdefault("venue_id", venue["id"])
        elements.append(add_element(program["id"], supplier["id"], **kwargs))
    contract = create_active_contract(
        program["id"], supplier["id"], **(contract_overrides or {})
    )
    return {
        "venue": venue,
        "supplier": supplier,
        "program": program,
        "elements": elements,
        "contract": contract,
    }


def setup_staff_member_with_confirmed_minutes(
    shift_windows,
    staff_overrides=None,
    program_overrides=None,
    segment_overrides=None,
    clock: str = CLOCK_STARTUP_UTC,
):
    """One staff member with one CONFIRMED shift per (starts_at, ends_at) pair
    in `shift_windows`, so `confirmed_minutes_total` accumulates. Returns
    `program`, `segment`, `staff`, `assignments`.
    """
    ctx = setup_locked_program_with_segment(
        program_overrides=program_overrides,
        segment_overrides=segment_overrides,
        clock=clock,
    )
    staff = create_staff_member(**(staff_overrides or {}))
    assignments = []
    for starts_at, ends_at in shift_windows:
        assignment = propose_assignment(
            staff["id"],
            ctx["program"]["id"],
            target_type="SEGMENT",
            segment_id=ctx["segment"]["id"],
            role_type=staff["role_type"],
            starts_at=starts_at,
            ends_at=ends_at,
        )
        assignments.append(confirm_assignment(assignment["id"]))
    ctx["staff"] = get_success_data(api_client.get_staff_member(staff["id"], PD))
    ctx["assignments"] = assignments
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: finalisation / terminal state
# ---------------------------------------------------------------------------
def open_settlement_payment(
    program_id: str,
    supplier_id: str,
    contract_id: str,
    user_id: str = CONTROLLER_APPROVER_USER_ID,
    expected_contract_version: int = None,
) -> dict:
    """Open a settlement payment against the contract's observed version."""
    if expected_contract_version is None:
        contract = get_success_data(
            api_client.get_supplier_contract(contract_id, make_controller_headers(user_id))
        )
        expected_contract_version = contract["version"]
    payload = create_settlement_payment_payload(
        program_id, supplier_id, contract_id, expected_contract_version
    )
    return get_success_data(
        api_client.create_settlement_payment(payload, make_controller_headers(user_id))
    )


def setup_pending_settlement(
    actual_headcount: int = 50,
    deliver_clock: str = "2026-09-13T14:30:00Z",
    program_overrides=None,
    element_overrides=None,
    contract_overrides=None,
    venue_overrides=None,
    supplier_overrides=None,
):
    """Run a programme to an issued invoice and then open one PENDING settlement
    payment against its ACTIVE contract. Returns the invoiced setup dict plus
    `payment`.
    """
    ctx = setup_invoiced_program(
        actual_headcount=actual_headcount,
        deliver_clock=deliver_clock,
        program_overrides=program_overrides,
        element_overrides=element_overrides,
        venue_overrides=venue_overrides,
        supplier_overrides=supplier_overrides,
        contract_overrides=contract_overrides,
    )
    ctx["payment"] = open_settlement_payment(
        ctx["program"]["id"], ctx["supplier"]["id"], ctx["contract"]["id"]
    )
    ctx["contract"] = get_success_data(
        api_client.get_supplier_contract(ctx["contract"]["id"], CTRL)
    )
    return ctx
