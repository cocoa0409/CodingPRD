"""Work orders: rework cycle, follow-up parenting, hold/resume, RBAC."""
from test_helpers import (
    ApiErrorId,
    activate_relocation,
    approve_relocation,
    arrive_ticket,
    create_work_order_payload,
    end_relocation,
    get_unit,
    get_work_order,
    list_ticket_work_orders,
    make_supervisor,
    make_supervisor_headers,
    make_technician,
    make_technician_headers,
    make_unit,
    mitigate_ticket,
    mitigated_ticket_with_work_order,
    propose_relocation,
    publish_shift,
    set_clock,
    start_shift,
    validate_error,
    validate_success,
)


def _setup_mitigated_with_work_order(unit_number):
    """Technician + supervisor + unit + ACTIVE shift + LEAK_MINOR ticket
    mitigated (unit habitable); returns (tech, sup, unit, ticket, work_order)."""
    set_clock("2026-08-03T00:00:00Z")
    tech = make_technician()
    sup = make_supervisor()
    unit = make_unit(unit_number=unit_number)
    shift = publish_shift(tech["id"], "2026-08-03T00:00:00Z",
                          "2026-08-03T12:00:00Z")
    start_shift(shift["id"])
    ticket, work_order = mitigated_ticket_with_work_order(
        unit["id"], tech["id"], "LEAK_MINOR",
        dispatch_at="2026-08-03T00:00:00Z",
        arrive_at="2026-08-03T00:30:00Z",
        mitigate_at="2026-08-03T01:00:00Z",
    )
    return tech, sup, unit, ticket, work_order


class TestWorkOrderReworkCycle:
    def test_work_order_reopen_reenters_assignment_path(self, api):
        """PRD §3.5: "From `COMPLETED`, a supervisor either verifies the work
        (`COMPLETED → VERIFIED`, terminal) or reopens it (`COMPLETED →
        REOPENED`, optionally carrying a `reason`), feeding the rework loop
        back into assignment."
        PRD §3.5: "Assignment is the `MaintenanceSupervisor`'s action and works
        from either `OPEN` or `REOPENED` (else `ERR_WORK_ORDER_INVALID_STATE`),
        writing `assigned_technician_id` and incrementing `version`."

        Design: Difficulty/non_linear_state_machine/work_order_completed_reopen_rerun_cycle
        """
        tech, sup, _unit, _ticket, wo = _setup_mitigated_with_work_order("U-401")
        sup_headers = make_supervisor_headers(sup["id"])
        tech_headers = make_technician_headers(tech["id"])

        assigned = validate_success(
            api.assign_work_order(wo["id"], {"technician_id": tech["id"]},
                                  sup_headers), 200)
        assert assigned["status"] == "ASSIGNED", "OPEN -> ASSIGNED"
        validate_success(api.begin_work_order(wo["id"], tech_headers), 200)
        completed = validate_success(
            api.complete_work_order(wo["id"], tech_headers), 200)
        assert completed["status"] == "COMPLETED", "first completion"
        reopened = validate_success(
            api.reopen_work_order(wo["id"], {"reason": "Trap still weeping"},
                                  sup_headers), 200)
        assert reopened["status"] == "REOPENED", "cycle back out of COMPLETED"
        reassigned = validate_success(
            api.assign_work_order(wo["id"], {"technician_id": tech["id"]},
                                  sup_headers), 200)
        assert reassigned["status"] == "ASSIGNED", (
            "REOPENED re-enters the assignment path"
        )

    def test_work_order_rework_cycle_terminates_at_verified(self, api):
        """PRD §3.5: "From `COMPLETED`, a supervisor either verifies the work
        (`COMPLETED → VERIFIED`, terminal) or reopens it (`COMPLETED →
        REOPENED`, optionally carrying a `reason`), feeding the rework loop
        back into assignment."

        Design: Difficulty/non_linear_state_machine/work_order_completed_reopen_rerun_cycle
        """
        tech, sup, _unit, _ticket, wo = _setup_mitigated_with_work_order("U-401")
        sup_headers = make_supervisor_headers(sup["id"])
        tech_headers = make_technician_headers(tech["id"])

        validate_success(
            api.assign_work_order(wo["id"], {"technician_id": tech["id"]},
                                  sup_headers), 200)
        validate_success(api.begin_work_order(wo["id"], tech_headers), 200)
        validate_success(api.complete_work_order(wo["id"], tech_headers), 200)
        validate_success(
            api.reopen_work_order(wo["id"], {"reason": "rework"}, sup_headers),
            200)
        validate_success(
            api.assign_work_order(wo["id"], {"technician_id": tech["id"]},
                                  sup_headers), 200)
        validate_success(api.begin_work_order(wo["id"], tech_headers), 200)
        validate_success(api.complete_work_order(wo["id"], tech_headers), 200)
        verified = validate_success(
            api.verify_work_order(wo["id"], sup_headers), 200)
        assert verified["status"] == "VERIFIED", "terminal after the rework loop"


def test_followup_parent_must_be_finished(api):
    """PRD §3.5: "An optional `parent_work_order_id` chains the order as a
    follow-up of an earlier one, but the parent must already be `COMPLETED` or
    `VERIFIED` — otherwise the create fails with
    `ERR_FOLLOWUP_PARENT_NOT_FINISHED`."

    Design: Corner/validations/followup_parent_must_be_finished
    """
    tech, sup, _unit, ticket, wo = _setup_mitigated_with_work_order("M-4")
    sup_headers = make_supervisor_headers(sup["id"])
    tech_headers = make_technician_headers(tech["id"])

    premature = api.create_work_order(
        create_work_order_payload(
            call_ticket_id=ticket["id"], title="premature follow-up",
            description="too early", parent_work_order_id=wo["id"],
        ),
        sup_headers,
    )
    validate_error(premature, ApiErrorId.ERR_FOLLOWUP_PARENT_NOT_FINISHED)

    validate_success(
        api.assign_work_order(wo["id"], {"technician_id": tech["id"]},
                              sup_headers), 200)
    validate_success(api.begin_work_order(wo["id"], tech_headers), 200)
    validate_success(api.complete_work_order(wo["id"], tech_headers), 200)
    validate_success(api.verify_work_order(wo["id"], sup_headers), 200)

    follow_up = validate_success(
        api.create_work_order(
            create_work_order_payload(
                call_ticket_id=ticket["id"], title="legit follow-up",
                description="after verify", parent_work_order_id=wo["id"],
            ),
            sup_headers,
        ),
        201,
    )
    assert follow_up["parent_work_order_id"] == wo["id"]
    assert follow_up["priority"] == "STANDARD"
    assert follow_up["status"] == "OPEN"


def test_work_order_hold_resume_roundtrip(api, dispatcher_headers):
    """PRD §3.7: "every work order on that unit in `OPEN` or `ASSIGNED` whose
    `priority` is not `EMERGENCY_FOLLOWUP` is placed `ON_HOLD` (emergency
    follow-ups keep moving)..."
    PRD §3.7: "Ending also restores the unit's `habitability_status` to
    `HABITABLE` and releases every `ON_HOLD` work order on the unit back to
    `OPEN` with `assigned_technician_id` cleared, then increments the case's
    `version`."

    Design: Corner/state_machines/work_order_hold_resume_roundtrip
    """
    set_clock("2026-08-01T00:00:00Z")
    tech = make_technician()
    sup = make_supervisor()
    unit = make_unit(unit_number="S-5", building_code="BS")
    shift = publish_shift(tech["id"], "2026-08-01T00:00:00Z",
                          "2026-08-01T08:00:00Z")
    start_shift(shift["id"])
    ticket, emergency_wo = mitigated_ticket_with_work_order(
        unit["id"], tech["id"], "FLOOD",
        dispatch_at="2026-08-01T00:00:00Z",
        mitigate_at="2026-08-01T01:00:00Z",
        unit_uninhabitable=True,
    )
    sup_headers = make_supervisor_headers(sup["id"])
    validate_success(api.cancel_work_order(emergency_wo["id"], sup_headers), 200)
    standard_wo = validate_success(
        api.create_work_order(
            create_work_order_payload(
                call_ticket_id=ticket["id"], title="Drywall replace",
                description="Replace lower drywall",
            ),
            sup_headers,
        ),
        201,
    )
    assigned = validate_success(
        api.assign_work_order(standard_wo["id"], {"technician_id": tech["id"]},
                              sup_headers), 200)
    assert assigned["status"] == "ASSIGNED"

    case = propose_relocation(unit["id"], ticket["id"], "2026-08-03T00:00:00Z",
                              "2026-08-05T00:00:00Z", 10000, tech["id"])
    approve_relocation(case["id"], sup_headers)
    held = get_work_order(standard_wo["id"])
    assert held["status"] == "ON_HOLD", "ASSIGNED is within the hold's catch set"

    set_clock("2026-08-03T09:00:00Z")
    activate_relocation(case["id"], sup)
    ended = end_relocation(case["id"], "2026-08-05T00:00:00Z", sup)
    assert ended["status"] == "ENDED"

    resumed = get_work_order(standard_wo["id"])
    assert resumed["status"] == "OPEN", "held order resumes to OPEN"
    assert resumed.get("assigned_technician_id") is None, (
        "resume clears the assignment"
    )
    assert get_unit(unit["id"])["habitability_status"] == "HABITABLE"


def test_dispatcher_cannot_assign_work_order(api, dispatcher_headers):
    """PRD §3.5: "Assignment is the `MaintenanceSupervisor`'s action and works
    from either `OPEN` or `REOPENED` (else `ERR_WORK_ORDER_INVALID_STATE`)..."
    PRD §2.1: "A request whose role is not in the endpoint's allowed set is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/dispatcher_cannot_assign_work_order
    """
    tech, _sup, _unit, _ticket, wo = _setup_mitigated_with_work_order("R-1")
    resp = api.assign_work_order(wo["id"], {"technician_id": tech["id"]},
                                 dispatcher_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_work_order(wo["id"])["status"] == "OPEN"


def test_supervisor_capability_gate_enforced(api):
    """PRD §2.1: "In addition, the backing `Technician` row must carry
    `capability` equal to `SUPERVISOR`; a `MaintenanceSupervisor` request whose
    technician row lacks that capability is rejected with
    `ERR_NOT_SUPERVISOR_CAPABLE` (HTTP 403)."

    Design: Corner/rbac/supervisor_capability_gate_enforced
    """
    tech, _sup, _unit, _ticket, wo = _setup_mitigated_with_work_order("R-7")
    # The acting id belongs to a TECHNICIAN-capability row, not a supervisor.
    resp = api.assign_work_order(
        wo["id"], {"technician_id": tech["id"]},
        make_supervisor_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_SUPERVISOR_CAPABLE)
    assert get_work_order(wo["id"])["status"] == "OPEN"
