"""
Composite state builders.

The harness restarts the API server before every individual test, so each test
begins against an empty database and must build every precondition it needs from
scratch through declared endpoints. These builders do that, in five tiers:

  Tier 1  reference data and the logical clock
  Tier 2  the entity hierarchy up to a placement in a chosen lifecycle state
  Tier 3  lifecycle shortcuts (addenda, attendance, invoices, transport, reports)
  Tier 4  accumulation and threshold targeting (paid-to-date, readiness scores)
  Tier 5  finalisation and terminal states (termination, return, remand)

Every builder drives the logical clock explicitly, starting from the epoch, and
uses get_success_data() so a broken precondition fails loudly as a setup error.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from . import factories as f
from .test_users import (
    COORDINATOR_HEADERS,
    FISCAL_OFFICER_HEADERS,
    HEARING_ADJUDICATOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    TEAM_CHAIR_HEADERS,
    make_parent_guardian_headers,
    make_school_billing_agent_headers,
)

ACTIVATION_INSTANT = "2026-09-01T08:00:00Z"


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 1 - the logical clock and reference data
# ═══════════════════════════════════════════════════════════════════════════════
def set_clock(api: ApiClient, instant: str) -> None:
    """Move the logical clock. Every fixture sets it explicitly from the epoch."""
    get_success_data(api.set_clock(instant, SYSTEM_ADMIN_HEADERS))


def reset_clock(api: ApiClient) -> None:
    """Pin the clock at the documented starting instant 2026-08-01T00:00:00Z."""
    set_clock(api, CLOCK_EPOCH)


def make_fiscal_account(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_fiscal_account(
            f.fiscal_account_payload(**overrides), FISCAL_OFFICER_HEADERS
        )
    )


def make_student(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_student(f.student_payload(**overrides), COORDINATOR_HEADERS)
    )


def make_school(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_private_school(
            f.private_school_payload(**overrides), SYSTEM_ADMIN_HEADERS
        )
    )


def make_rate_schedule(
    api: ApiClient, school: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """
    Publish a rate schedule against the school's current version.

    The school version is re-read rather than taken from the caller's stale copy,
    because a STATE_APPROVED publication repoints active_rate_schedule_id and
    bumps the school row.
    """
    fresh = get_success_data(api.get_private_school(school["id"], FISCAL_OFFICER_HEADERS))
    return get_success_data(
        api.create_rate_schedule(
            f.rate_schedule_payload(school["id"], fresh["version"], **overrides),
            FISCAL_OFFICER_HEADERS,
        )
    )


def make_transport_route(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_transport_route(
            f.transport_route_payload(**overrides), COORDINATOR_HEADERS
        )
    )


def build_reference_data(
    api: ApiClient,
    *,
    account_overrides: Optional[Dict[str, Any]] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    school_overrides: Optional[Dict[str, Any]] = None,
    rate_overrides: Optional[Dict[str, Any]] = None,
    reset: bool = True,
) -> Dict[str, Any]:
    """
    Clock at the epoch, one funded account, one student, one approved school with a
    STATE_APPROVED FY2027 rate schedule. This is the floor every other tier sits on.
    """
    if reset:
        reset_clock(api)
    account = make_fiscal_account(api, **(account_overrides or {}))
    student = make_student(api, **(student_overrides or {}))
    school = make_school(api, **(school_overrides or {}))
    schedule = make_rate_schedule(api, school, **(rate_overrides or {}))
    return {
        "account": account,
        "student": student,
        "school": school,
        "schedule": schedule,
        "school_headers": make_school_billing_agent_headers(school["id"]),
        "parent_headers": make_parent_guardian_headers(student["id"]),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 2 - the entity hierarchy up to a placement in a chosen state
# ═══════════════════════════════════════════════════════════════════════════════
def make_approved_decision(
    api: ApiClient,
    student_id: str,
    *,
    residential: bool = False,
    **overrides,
) -> Dict[str, Any]:
    """Draft, submit and approve one decision. The chair differs from the author."""
    payload = (
        f.residential_decision_payload(student_id, **overrides)
        if residential
        else f.placement_decision_payload(student_id, **overrides)
    )
    decision = get_success_data(
        api.create_placement_decision(payload, COORDINATOR_HEADERS)
    )
    get_success_data(
        api.submit_placement_decision(decision["id"], COORDINATOR_HEADERS)
    )
    return get_success_data(
        api.approve_placement_decision(
            decision["id"], TEAM_CHAIR_HEADERS, f.reviewer_notes_payload()
        )
    )


def make_proposed_placement(
    api: ApiClient,
    ref: Dict[str, Any],
    *,
    decision: Optional[Dict[str, Any]] = None,
    student: Optional[Dict[str, Any]] = None,
    residential: bool = False,
    **overrides,
) -> Dict[str, Any]:
    """Propose a placement against an approved decision. Nothing is encumbered yet."""
    subject = student or ref["student"]
    dec = decision or make_approved_decision(
        api, subject["id"], residential=residential
    )
    payload = f.placement_payload(
        subject["id"],
        ref["school"]["id"],
        dec["id"],
        ref["schedule"]["id"],
        ref["account"]["id"],
        **overrides,
    )
    placement = get_success_data(api.create_placement(payload, COORDINATOR_HEADERS))
    placement["_decision_id"] = dec["id"]
    return placement


def make_contracted_placement(
    api: ApiClient, ref: Dict[str, Any], **kwargs
) -> Dict[str, Any]:
    """Propose then execute the contract, booking the tuition encumbrance."""
    placement = make_proposed_placement(api, ref, **kwargs)
    contracted = get_success_data(
        api.execute_contract(placement["id"], FISCAL_OFFICER_HEADERS)
    )
    contracted["_decision_id"] = placement["_decision_id"]
    return contracted


def make_active_placement(
    api: ApiClient,
    ref: Dict[str, Any],
    *,
    activation_instant: str = ACTIVATION_INSTANT,
    **kwargs,
) -> Dict[str, Any]:
    """
    Execute the contract, move the clock into the activation grace window, activate.

    The clock must sit on or after the placement's start_date and within the grace
    window for activation to be legal, so the instant is set explicitly.
    """
    placement = make_contracted_placement(api, ref, **kwargs)
    set_clock(api, activation_instant)
    active = get_success_data(
        api.activate_placement(placement["id"], COORDINATOR_HEADERS)
    )
    active["_decision_id"] = placement["_decision_id"]
    return active


def make_active_placement_with_transport(
    api: ApiClient,
    ref: Dict[str, Any],
    route: Dict[str, Any],
    *,
    activation_instant: str = ACTIVATION_INSTANT,
    assignment_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Contract the placement, seat its rider on the route, then activate.

    Activation of a placement whose `transportation_required` is true additionally
    requires that at least one transportation assignment on that placement is
    already `ACTIVE`, and a seat may only be requested while the placement is
    `CONTRACTED` or `ACTIVE`. The seat therefore has to be booked between contract
    execution and activation, which is the only ordering that reaches an ACTIVE
    placement carrying transportation.

    Returns the activated placement and its assignment.
    """
    kwargs.setdefault("transportation_required", True)
    placement = make_contracted_placement(api, ref, **kwargs)
    assignment = assign_transport(
        api, placement["id"], route["id"], **(assignment_overrides or {})
    )
    set_clock(api, activation_instant)
    active = get_success_data(
        api.activate_placement(placement["id"], COORDINATOR_HEADERS)
    )
    active["_decision_id"] = placement["_decision_id"]
    return active, assignment


def build_active_day_placement(
    api: ApiClient,
    *,
    account_overrides: Optional[Dict[str, Any]] = None,
    student_overrides: Optional[Dict[str, Any]] = None,
    school_overrides: Optional[Dict[str, Any]] = None,
    rate_overrides: Optional[Dict[str, Any]] = None,
    placement_overrides: Optional[Dict[str, Any]] = None,
    activation_instant: str = ACTIVATION_INSTANT,
    route_overrides: Optional[Dict[str, Any]] = None,
    assignment_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    The canonical world: funded account, student, approved school with rates, an
    approved DAY decision and one ACTIVE placement of 180 instructional days.

    When the placement requires transportation, a route is created and its seat is
    taken before activation, because activation is gated on an ACTIVE assignment;
    the route and the assignment are returned under the "route" and "assignment"
    keys.
    """
    ref = build_reference_data(
        api,
        account_overrides=account_overrides,
        student_overrides=student_overrides,
        school_overrides=school_overrides,
        rate_overrides=rate_overrides,
    )
    overrides = dict(placement_overrides or {})
    if overrides.get("transportation_required"):
        ref["route"] = make_transport_route(api, **(route_overrides or {}))
        placement, assignment = make_active_placement_with_transport(
            api,
            ref,
            ref["route"],
            activation_instant=activation_instant,
            assignment_overrides=assignment_overrides,
            **overrides,
        )
        ref["assignment"] = assignment
    else:
        placement = make_active_placement(
            api,
            ref,
            activation_instant=activation_instant,
            **overrides,
        )
    ref["placement"] = placement
    ref["decision_id"] = placement["_decision_id"]
    return ref


def build_contracted_day_placement(
    api: ApiClient,
    *,
    account_overrides: Optional[Dict[str, Any]] = None,
    placement_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """The same world stopped one step earlier, at CONTRACTED."""
    ref = build_reference_data(api, account_overrides=account_overrides, **kwargs)
    placement = make_contracted_placement(api, ref, **(placement_overrides or {}))
    ref["placement"] = placement
    ref["decision_id"] = placement["_decision_id"]
    return ref


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 3 - lifecycle shortcuts
# ═══════════════════════════════════════════════════════════════════════════════
def add_authorized_addendum(
    api: ApiClient, placement_id: str, **overrides
) -> Dict[str, Any]:
    """Propose an addendum and authorize it, pinning its rate and encumbrance."""
    addendum = get_success_data(
        api.create_service_addendum(
            f.service_addendum_payload(placement_id, **overrides), COORDINATOR_HEADERS
        )
    )
    return get_success_data(
        api.authorize_service_addendum(addendum["id"], FISCAL_OFFICER_HEADERS)
    )


def add_two_authorized_addenda(
    api: ApiClient, placement_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    The two-addendum shape used by the invoice arithmetic fixtures: SPEECH at
    2.0 hours a week and Medicaid billable, OT at 1.5 hours a week and not.
    """
    speech = add_authorized_addendum(
        api,
        placement_id,
        service_type="SPEECH",
        authorized_hours_per_week=2.0,
        contract_weeks=36,
        medicaid_billable=True,
    )
    ot = add_authorized_addendum(
        api,
        placement_id,
        service_type="OT",
        authorized_hours_per_week=1.5,
        contract_weeks=36,
        medicaid_billable=False,
    )
    return speech, ot


def file_attendance(
    api: ApiClient, ref: Dict[str, Any], placement_id: str, **overrides
) -> Dict[str, Any]:
    """File a twenty-eight-day record as the school that holds the placement."""
    return get_success_data(
        api.create_attendance_record(
            f.attendance_record_payload(placement_id, **overrides),
            ref["school_headers"],
        )
    )


def verify_attendance(
    api: ApiClient, record_id: str, decision: str = "ACCEPT", **overrides
) -> Dict[str, Any]:
    """District staff dispose of a submitted record; ACCEPT rolls the hours up."""
    return get_success_data(
        api.verify_attendance_record(
            record_id, f.verify_attendance_payload(decision, **overrides),
            COORDINATOR_HEADERS,
        )
    )


def file_verified_attendance(
    api: ApiClient, ref: Dict[str, Any], placement_id: str, **overrides
) -> Dict[str, Any]:
    record = file_attendance(api, ref, placement_id, **overrides)
    return verify_attendance(api, record["id"])


def placement_version(api: ApiClient, placement_id: str) -> int:
    """Read the placement's current version for the invoice stale-view guard."""
    fresh = get_success_data(api.get_placement(placement_id, FISCAL_OFFICER_HEADERS))
    return fresh["version"]


def create_invoice(
    api: ApiClient,
    ref: Dict[str, Any],
    placement_id: str,
    attendance_record_id: str,
    submitted_amount_cents: int,
    **overrides,
) -> Dict[str, Any]:
    """
    Submit an invoice as the school, quoting the placement version the guard wants.

    The version is always re-read immediately before the call because cascades from
    earlier steps advance the placement row.
    """
    version = overrides.pop(
        "expected_placement_version", placement_version(api, placement_id)
    )
    return get_success_data(
        api.create_tuition_invoice(
            f.tuition_invoice_payload(
                placement_id,
                attendance_record_id,
                submitted_amount_cents,
                version,
                **overrides,
            ),
            ref["school_headers"],
        )
    )


def verify_invoice(
    api: ApiClient, invoice_id: str, basis: str = "ENROLLMENT"
) -> Dict[str, Any]:
    """Price the invoice under the chosen basis; the coordinator becomes verifier."""
    return get_success_data(
        api.verify_tuition_invoice(
            invoice_id, f.verify_invoice_payload(basis), COORDINATOR_HEADERS
        )
    )


def approve_payment(api: ApiClient, invoice_id: str) -> Dict[str, Any]:
    """
    Approve payment as a fiscal officer.

    The verifier above is a placement coordinator, so the acting user here differs
    from the recorded verified_by_user_id and the segregation pair is satisfied.
    """
    return get_success_data(
        api.approve_invoice_payment(invoice_id, FISCAL_OFFICER_HEADERS)
    )


def assign_transport(
    api: ApiClient, placement_id: str, route_id: str, **overrides
) -> Dict[str, Any]:
    """Request transportation; the server assigns a seat or waitlists the rider."""
    return get_success_data(
        api.create_transportation_assignment(
            f.transportation_assignment_payload(placement_id, route_id, **overrides),
            COORDINATOR_HEADERS,
        )
    )


def release_transport(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    """Release an assignment, freeing its seat and running waitlist promotion."""
    return get_success_data(
        api.release_transportation_assignment(assignment_id, COORDINATOR_HEADERS)
    )


def submit_progress_report(
    api: ApiClient, placement_id: str, quarter: int, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_progress_report(
            f.progress_report_payload(placement_id, quarter, **overrides),
            COORDINATOR_HEADERS,
        )
    )


def accept_progress_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.accept_progress_report(
            report_id, f.accept_report_payload("ACCEPT"), COORDINATOR_HEADERS
        )
    )


def submit_accepted_report(
    api: ApiClient, placement_id: str, quarter: int, **overrides
) -> Dict[str, Any]:
    report = submit_progress_report(api, placement_id, quarter, **overrides)
    return accept_progress_report(api, report["id"])


def make_draft_plan(api: ApiClient, placement_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_transition_plan(
            f.transition_plan_payload(placement_id, **overrides), COORDINATOR_HEADERS
        )
    )


def activate_plan(api: ApiClient, plan_id: str, **overrides) -> Dict[str, Any]:
    """Activate the plan as the team chair, reserving the transition commitment."""
    return get_success_data(
        api.activate_transition_plan(
            plan_id, f.activate_plan_payload(**overrides), TEAM_CHAIR_HEADERS
        )
    )


def file_claim(
    api: ApiClient, ref: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """File a unilateral-placement reimbursement claim as the student's guardian."""
    return get_success_data(
        api.create_reimbursement_claim(
            f.reimbursement_claim_payload(
                ref["student"]["id"], ref["account"]["id"], **overrides
            ),
            ref["parent_headers"],
        )
    )


def adjudicate_claim(
    api: ApiClient, claim_id: str, award_basis: str = "strict_statutory", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_reimbursement_claim(
            claim_id,
            f.adjudicate_payload(award_basis, **overrides),
            HEARING_ADJUDICATOR_HEADERS,
        )
    )


def remand_claim(api: ApiClient, claim_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.remand_reimbursement_claim(
            claim_id, f.remand_payload(**overrides), HEARING_ADJUDICATOR_HEADERS
        )
    )


def file_funding_claim(
    api: ApiClient, placement_id: str, claim_type: str = "HIGH_COST_FUND", **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_funding_claim(
            f.funding_claim_payload(placement_id, claim_type, **overrides),
            FISCAL_OFFICER_HEADERS,
        )
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 4 - accumulation and threshold targeting
# ═══════════════════════════════════════════════════════════════════════════════
ATTENDANCE_FILING_INSTANT = "2026-11-02T09:00:00Z"

FULL_MONTH_PERIOD = {"period_start": "2026-10-05", "period_end": "2026-11-01"}


def build_two_addenda_world(
    api: ApiClient, **kwargs
) -> Dict[str, Any]:
    """
    An ACTIVE DAY placement carrying two authorized addenda.

    This is the shape the invoice arithmetic depends on: a SPEECH addendum at 2.0
    hours a week and an OT addendum at 1.5 hours a week, both for 36 weeks.
    """
    world = build_active_day_placement(api, **kwargs)
    speech, ot = add_two_authorized_addenda(api, world["placement"]["id"])
    world["speech"] = speech
    world["ot"] = ot
    return world


def build_two_addenda_billing_cycle(
    api: ApiClient,
    *,
    days_attended: int = 16,
    days_absent_unexcused: int = 4,
    filing_instant: str = ATTENDANCE_FILING_INSTANT,
    **kwargs,
) -> Dict[str, Any]:
    """
    The two-addendum world plus one VERIFIED twenty-eight-day record carrying 7.5
    hours on the speech addendum and 5.5 hours on the OT addendum.
    """
    world = build_two_addenda_world(api, **kwargs)
    set_clock(api, filing_instant)
    record = file_attendance(
        api,
        world,
        world["placement"]["id"],
        days_enrolled=20,
        days_attended=days_attended,
        days_absent_unexcused=days_absent_unexcused,
        residential_nights=0,
        service_delivery_lines=[
            f.service_line(world["speech"]["id"], 7.5),
            f.service_line(world["ot"]["id"], 5.5),
        ],
        **FULL_MONTH_PERIOD,
    )
    world["record"] = verify_attendance(api, record["id"])
    return world


def build_simple_billing_cycle(
    api: ApiClient,
    *,
    days_enrolled: int = 20,
    days_attended: int = 20,
    days_absent_unexcused: int = 0,
    filing_instant: str = ATTENDANCE_FILING_INSTANT,
    **kwargs,
) -> Dict[str, Any]:
    """An ACTIVE DAY placement plus one VERIFIED record with no service lines."""
    world = build_active_day_placement(api, **kwargs)
    set_clock(api, filing_instant)
    record = file_attendance(
        api,
        world,
        world["placement"]["id"],
        days_enrolled=days_enrolled,
        days_attended=days_attended,
        days_absent_unexcused=days_absent_unexcused,
        residential_nights=0,
        service_delivery_lines=[],
        **FULL_MONTH_PERIOD,
    )
    world["record"] = verify_attendance(api, record["id"])
    return world


def bill_and_settle_cycle(
    api: ApiClient,
    world: Dict[str, Any],
    *,
    period_start: str,
    period_end: str,
    filing_instant: str,
    submitted_amount_cents: int,
    basis: str = "ENROLLMENT",
    days_enrolled: int = 28,
    days_attended: int = 28,
    days_absent_unexcused: int = 0,
    residential_nights: int = 0,
    transport_days_billed: int = 0,
    settle: bool = True,
) -> Dict[str, Any]:
    """
    One complete billing cycle: file, verify, invoice, price and optionally pay.

    Used to drive paid_total_ytd_cents up towards the high-cost trigger one
    twenty-eight-day period at a time.
    """
    set_clock(api, filing_instant)
    placement_id = world["placement"]["id"]
    record = file_attendance(
        api,
        world,
        placement_id,
        period_start=period_start,
        period_end=period_end,
        days_enrolled=days_enrolled,
        days_attended=days_attended,
        days_absent_unexcused=days_absent_unexcused,
        residential_nights=residential_nights,
        service_delivery_lines=[],
    )
    verify_attendance(api, record["id"])
    invoice = create_invoice(
        api,
        world,
        placement_id,
        record["id"],
        submitted_amount_cents,
        billing_period_start=period_start,
        billing_period_end=period_end,
        transport_days_billed=transport_days_billed,
    )
    invoice = verify_invoice(api, invoice["id"], basis)
    if settle:
        invoice = approve_payment(api, invoice["id"])
    return {"record": record, "invoice": invoice}


def build_readiness_world(
    api: ApiClient,
    report_specs: List[Dict[str, Any]],
    *,
    accept: bool = True,
    plan_instant: Optional[str] = None,
    plan_overrides: Optional[Dict[str, Any]] = None,
    addenda: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """
    An ACTIVE placement with a chosen set of quarterly progress reports and a DRAFT
    return-transition plan.

    Each entry of report_specs is a progress-report payload fragment, so a caller
    can target an exact readiness aggregate by pinning goals, benchmark and
    attendance figures per quarter. The final report may be left SUBMITTED to test
    the accepted-report count floor.
    """
    world = build_two_addenda_world(api, **kwargs) if addenda else build_active_day_placement(api, **kwargs)
    placement_id = world["placement"]["id"]
    reports = []
    for index, spec in enumerate(report_specs, start=1):
        quarter = spec.pop("quarter", index)
        leave_submitted = spec.pop("leave_submitted", not accept)
        report = submit_progress_report(api, placement_id, quarter, **spec)
        if not leave_submitted:
            report = accept_progress_report(api, report["id"])
        reports.append(report)
    world["reports"] = reports
    if plan_instant:
        set_clock(api, plan_instant)
    world["plan"] = make_draft_plan(
        api, placement_id, **(plan_overrides or {})
    )
    return world


def build_route_pair_world(
    api: ApiClient,
    *,
    route_overrides: Optional[Dict[str, Any]] = None,
    second_student_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    One route and two CONTRACTED placements for two different students, both
    requiring transportation. This is the shape seat competition and waitlist
    promotion need.
    """
    ref = build_reference_data(api)
    first = make_contracted_placement(api, ref, transportation_required=True)
    second_student = make_student(api, **(second_student_overrides or {}))
    second = make_contracted_placement(
        api, ref, student=second_student, transportation_required=True
    )
    route = make_transport_route(api, **(route_overrides or {}))
    ref["placement_a"] = first
    ref["placement_b"] = second
    ref["student_b"] = second_student
    ref["route"] = route
    return ref


# ═══════════════════════════════════════════════════════════════════════════════
# Tier 5 - finalisation and terminal states
# ═══════════════════════════════════════════════════════════════════════════════
def terminate_placement(
    api: ApiClient, placement_id: str, **overrides
) -> Dict[str, Any]:
    """Terminate an ACTIVE placement, firing the full termination cascade."""
    return get_success_data(
        api.terminate_placement(
            placement_id, f.termination_payload(**overrides), COORDINATOR_HEADERS
        )
    )


def return_placement_to_district(
    api: ApiClient, placement_id: str, **overrides
) -> Dict[str, Any]:
    """Close an ACTIVE placement by returning the student to a district program."""
    return get_success_data(
        api.return_to_district(
            placement_id, f.return_to_district_payload(**overrides), COORDINATOR_HEADERS
        )
    )


def build_awarded_claim_world(
    api: ApiClient,
    *,
    award_basis: str = "strict_statutory",
    claim_overrides: Optional[Dict[str, Any]] = None,
    adjudicate_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    A funded account, one student with no district placement at all, and one
    adjudicated reimbursement claim. No placement exists, so nothing is encumbered
    and the award moves cents straight from available to disbursed.
    """
    reset_clock(api)
    account = make_fiscal_account(api)
    student = make_student(api)
    ref = {
        "account": account,
        "student": student,
        "parent_headers": make_parent_guardian_headers(student["id"]),
    }
    claim = file_claim(api, ref, **(claim_overrides or {}))
    ref["claim"] = adjudicate_claim(
        api, claim["id"], award_basis, **(adjudicate_overrides or {})
    )
    return ref


# ═══════════════════════════════════════════════════════════════════════════════
# Read helpers used by assertions
# ═══════════════════════════════════════════════════════════════════════════════
def read_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_fiscal_account(account_id, FISCAL_OFFICER_HEADERS))


def read_placement(api: ApiClient, placement_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_placement(placement_id, FISCAL_OFFICER_HEADERS))


def read_student(api: ApiClient, student_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_student(student_id, COORDINATOR_HEADERS))


def read_school(api: ApiClient, school_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_private_school(school_id, COORDINATOR_HEADERS))


def read_addendum(api: ApiClient, addendum_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_service_addendum(addendum_id, FISCAL_OFFICER_HEADERS)
    )


def read_route(api: ApiClient, route_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_transport_route(route_id, COORDINATOR_HEADERS))


def read_assignment(api: ApiClient, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_transportation_assignment(assignment_id, COORDINATOR_HEADERS)
    )


def read_attendance(api: ApiClient, record_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_attendance_record(record_id, COORDINATOR_HEADERS)
    )


def read_invoice(api: ApiClient, invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_tuition_invoice(invoice_id, FISCAL_OFFICER_HEADERS))


def read_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_reimbursement_claim(claim_id, HEARING_ADJUDICATOR_HEADERS)
    )


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_transition_plan(plan_id, COORDINATOR_HEADERS))


def read_report(api: ApiClient, report_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_progress_report(report_id, COORDINATOR_HEADERS))


def read_funding_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_funding_claim(claim_id, FISCAL_OFFICER_HEADERS))


def read_decision(api: ApiClient, decision_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_placement_decision(decision_id, COORDINATOR_HEADERS)
    )


def read_readiness(
    api: ApiClient, plan_id: str, variant: Optional[str] = None
) -> Dict[str, Any]:
    params = {"variant": variant} if variant else None
    return get_success_data(
        api.get_plan_readiness(plan_id, COORDINATOR_HEADERS, params)
    )


def list_rows(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate a list response and return its rows and pagination meta."""
    return validate_paginated(response)
