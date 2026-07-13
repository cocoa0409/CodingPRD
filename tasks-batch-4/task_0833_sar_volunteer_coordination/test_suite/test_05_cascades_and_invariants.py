"""Transitive cascades (incident cancel depth-3, task suspend depth-2) and the two
conserved quantities (resource assignment count, incident reimbursement ledger)."""
from test_helpers import (
    validate_success, TEST_USERS,
    create_active_incident, create_demobilizing_incident, create_team_and_member,
    create_assigned_task, create_task, create_deployed_callout,
    create_resource, create_resource_assignment, create_active_resource_assignment,
    create_submitted_claim,
    setup_task_in_progress_with_member,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# --- Difficulty: transitive_cascade / incident_cancel_cascade_depth3 ---

def _active_incident_with_deployed_member(api, ics):
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc = create_active_incident(api, name="Cascade Search", ics_incident_number=ics)
    team, member = create_team_and_member(api)
    task = create_assigned_task(api, inc["id"], segment_area_sqkm=5.0, planned_searcher_hours=4)
    co = create_deployed_callout(api, task["id"], member["id"])
    return inc, member, task, co


def test_incident_cancel_cascades_to_task_and_incident_terminal(api):
    """PRD §3.1: "First, every task of the incident whose status is `DRAFT`,
    `ASSIGNED`, `IN_PROGRESS`, or `SUSPENDED` is driven to `CANCELLED`."

    Design: Difficulty/transitive_cascade/incident_cancel_cascade_depth3
    """
    inc, member, task, co = _active_incident_with_deployed_member(api, "OR-2026-0007")
    cancelled = validate_success(api.cancel_incident(inc["id"], IC))
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_task(task["id"], COORD))["status"] == "CANCELLED"


def test_incident_cancel_cascade_demobilizes_callout_and_restores_member(api):
    """PRD §3.1: "every non-terminal callout on the task is demobilized, each member
    who was `DEPLOYED` through such a callout is restored to `ACTIVE` (when they hold
    no other `DEPLOYED` callout), and every `RESERVED` or `ACTIVE` resource
    assignment on the task is cancelled with its resource's `active_assignment_count`
    decremented."

    Design: Difficulty/transitive_cascade/incident_cancel_cascade_depth3
    """
    inc, member, task, co = _active_incident_with_deployed_member(api, "OR-2026-0007b")
    validate_success(api.cancel_incident(inc["id"], IC))
    assert validate_success(api.get_callout(co["id"], COORD))["status"] == "DEMOBILIZED"
    assert validate_success(api.get_member(member["id"], COORD))["status"] == "ACTIVE"


# --- Difficulty: transitive_cascade / task_suspend_cascade_depth2 ---

def _in_progress_task_with_active_assignment(api, ics):
    inc, team, member, task, co = setup_task_in_progress_with_member(
        api, incident_overrides={"name": "Air Support", "incident_type": "AIR_SEARCH",
                                 "ics_incident_number": ics},
        task_overrides={"task_type": "AIR_RECON", "segment_area_sqkm": 20.0,
                        "planned_searcher_hours": 4},
        member_role="PILOT")
    resource = create_resource(api, name="Helo N123", resource_type="HELICOPTER")
    asg = create_active_resource_assignment(
        api, resource["id"], task["id"], resource["version"],
        window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T11:00:00Z")
    return inc, task, resource, asg


def test_task_suspend_releases_active_assignment(api):
    """PRD §3.3: "Suspension carries a cascade — every `ACTIVE` resource assignment
    on the task is released to `RELEASED`, and each such release decrements its
    resource's `active_assignment_count`, with the resource recomputed to `AVAILABLE`
    when its count reaches zero."

    Design: Difficulty/transitive_cascade/task_suspend_cascade_depth2
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc, task, resource, asg = _in_progress_task_with_active_assignment(api, "OR-2026-0008")
    suspended = validate_success(api.suspend_task(task["id"], COORD))
    assert suspended["status"] == "SUSPENDED"
    assert validate_success(api.get_resource_assignment(asg["id"], COORD))["status"] == "RELEASED"


def test_task_suspend_decrements_resource_count_to_available(api):
    """PRD §3.3: "each such release decrements its resource's
    `active_assignment_count`, with the resource recomputed to `AVAILABLE` when its
    count reaches zero."

    Design: Difficulty/transitive_cascade/task_suspend_cascade_depth2
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc, task, resource, asg = _in_progress_task_with_active_assignment(api, "OR-2026-0008b")
    validate_success(api.suspend_task(task["id"], COORD))
    res = validate_success(api.get_resource(resource["id"], COORD))
    assert res["active_assignment_count"] == 0
    assert res["status"] == "AVAILABLE"


# --- Difficulty: compensating_invariant / resource_assignment_count_conserved ---

def _resource_with_reserved_assignment(api, ics):
    inc = create_active_incident(api, name="Invariant Res", incident_type="AIR_SEARCH",
                                 ics_incident_number=ics)
    task = create_task(api, inc["id"], task_type="AIR_RECON", segment_area_sqkm=20.0,
                       planned_searcher_hours=4, planned_start="2026-05-02T06:00:00Z",
                       planned_end="2026-05-02T20:00:00Z")
    resource = create_resource(api, name="Boat B1", resource_type="BOAT")
    asg = create_resource_assignment(api, resource["id"], task["id"], resource["version"],
                                     window_start="2026-05-02T09:00:00Z",
                                     window_end="2026-05-02T11:00:00Z")
    return resource, asg


def test_reserve_then_cancel_conserves_resource_count(api):
    """PRD §2.6: "Whenever a claim is approved, rejected from approval, or a resource
    assignment is created, released, or cancelled, the corresponding conserved
    quantity is adjusted by exactly the compensating amount so that the ledger and
    the count never drift."

    Design: Difficulty/compensating_invariant/resource_assignment_count_conserved
    """
    resource, asg = _resource_with_reserved_assignment(api, "OR-2026-0017")
    validate_success(api.cancel_resource_assignment(asg["id"], COORD))
    res = validate_success(api.get_resource(resource["id"], COORD))
    assert res["active_assignment_count"] == 0


def test_cancel_reserved_assignment_returns_resource_available(api):
    """PRD §3.5: "cancelling a reserved assignment moves it from `RESERVED` to
    `CANCELLED`; both decrement the resource's `active_assignment_count`, with the
    resource recomputed to `AVAILABLE` once the count reaches zero."

    Design: Difficulty/compensating_invariant/resource_assignment_count_conserved
    """
    resource, asg = _resource_with_reserved_assignment(api, "OR-2026-0017b")
    cancelled = validate_success(api.cancel_resource_assignment(asg["id"], COORD))
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_resource(resource["id"], COORD))["status"] == "AVAILABLE"


# --- Difficulty: compensating_invariant / reimbursement_ledger_conserved ---

def _demobilizing_incident_with_approved_claim(api, ics):
    inc = create_demobilizing_incident(api, name="Ledger Inc", incident_type="URBAN",
                                       ics_incident_number=ics)
    team, member = create_team_and_member(api)
    claim = create_submitted_claim(api, member["id"], inc["id"], declared_mileage_miles=40,
                                   meal_count=2, lodging_nights=1)
    approved = validate_success(api.approve_claim(claim["id"], FIN))
    return inc, claim, approved


def test_reject_from_approved_reverses_ledger_to_zero(api):
    """PRD §3.8: "when the rejection comes from `APPROVED`, the earlier ledger credit
    is reversed by decreasing the incident's `total_approved_reimbursement_cents` by
    that claim's `final_amount_cents`, restoring the pre-approval total."

    Design: Difficulty/compensating_invariant/reimbursement_ledger_conserved
    """
    inc, claim, approved = _demobilizing_incident_with_approved_claim(api, "OR-2026-0018")
    # 0 tracks => reconciled mileage 0; meal 2*1500 + lodging 1*9000 = 12000
    assert approved["final_amount_cents"] == 12000
    rejected = validate_success(api.reject_claim(claim["id"], FIN))
    assert rejected["status"] == "REJECTED"
    inc_read = validate_success(api.get_incident(inc["id"], COORD))
    assert inc_read["total_approved_reimbursement_cents"] == 0


def test_approve_credits_ledger_before_reversal(api):
    """PRD §3.8: "Approval also credits the incident ledger: the incident's
    `total_approved_reimbursement_cents` is increased by the claim's
    `final_amount_cents`."

    Design: Difficulty/compensating_invariant/reimbursement_ledger_conserved
    """
    inc, claim, approved = _demobilizing_incident_with_approved_claim(api, "OR-2026-0018b")
    inc_read = validate_success(api.get_incident(inc["id"], COORD))
    assert inc_read["total_approved_reimbursement_cents"] == 12000
