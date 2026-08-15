"""Incident lifecycle, corrective-action discipline, and the two
segregation-of-duties pins (investigator vs reporter, verifier vs completer)."""
from test_helpers import (
    CO,
    ApiErrorId,
    api_client,
    assert_incident,
    create_employee,
    create_open_action,
    create_reported_incident,
    create_under_investigation_incident,
    get_incident,
    make_operator_headers,
    setup_incident_cast,
    setup_incident_with_action,
    validate_error,
    validate_success,
)


class TestIncidentReopenCycle:

    def _closed_incident(self):
        facility, reporter, investigator, assignee = setup_incident_cast()
        incident = create_under_investigation_incident(
            facility["id"], reporter["id"], investigator["id"],
            severity="NEAR_MISS", description="ammonia odor near valve")
        closed = validate_success(api_client.close_incident(incident["id"], CO),
                                  expected_status=200)
        return facility, reporter, investigator, closed

    def test_incident_reopen_cycle_statuses(self):
        """PRD section 3.6: "From `UNDER_INVESTIGATION`, a `ComplianceOfficer`'s
        close succeeds only while the pending count is zero — which, since the
        first action would have advanced the incident, means no corrective
        actions exist."
        PRD section 3.6: "a `ComplianceOfficer` may reopen it with a `reason`,
        moving `CLOSED` to `REOPENED`, incrementing its `reopen_count` (which
        starts at 0), raising `open_incident_count` once more, and recomputing
        posture — after which a fresh investigator assignment returns it to
        `UNDER_INVESTIGATION`."

        Design: Difficulty/non_linear_state_machine/incident_reopen_cycle
        """
        facility, reporter, investigator, closed = self._closed_incident()
        assert closed["status"] == "CLOSED"

        reopened = validate_success(
            api_client.reopen_incident(
                closed["id"], {"reason": "new evidence from vibration logs"}, CO),
            expected_status=200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1

        reassigned = validate_success(
            api_client.assign_investigator(
                closed["id"], {"investigator_employee_id": investigator["id"]}, CO),
            expected_status=200)
        assert reassigned["status"] == "UNDER_INVESTIGATION"

    def test_incident_reopen_cycle_open_count(self):
        """PRD section 3.6: "A new incident stands `REPORTED`; the facility's
        `open_incident_count` increments and its posture recomputes."
        PRD section 3.6: "Either close decrements the facility's
        `open_incident_count` and recomputes its posture."
        PRD section 2.7: "The `open_incident_count` tallies the facility's
        incidents in any non-closed state — `REPORTED`, `UNDER_INVESTIGATION`,
        `ACTIONS_ASSIGNED`, or `REOPENED`."

        Design: Difficulty/non_linear_state_machine/incident_reopen_cycle
        """
        facility, reporter, investigator, closed = self._closed_incident()
        after_close = validate_success(api_client.get_facility(facility["id"], CO),
                                       expected_status=200)
        assert after_close["open_incident_count"] == 0

        validate_success(
            api_client.reopen_incident(
                closed["id"], {"reason": "new evidence from vibration logs"}, CO),
            expected_status=200)
        after_reopen = validate_success(api_client.get_facility(facility["id"], CO),
                                        expected_status=200)
        # REOPENED is back in the open set: close dropped it to 0, reopen re-adds
        assert after_reopen["open_incident_count"] == 1


class TestCloseRequiresVerifiedActions:

    def test_incident_close_blocked_by_unverified_action(self):
        """PRD section 3.6: "From `ACTIONS_ASSIGNED`, close requires every
        action `VERIFIED`; a nonzero `pending_action_count` is rejected with
        `ERR_ACTIONS_OPEN` (409)."

        Design: Difficulty/cross_entity_state_dependency/incident_close_requires_actions_verified
        """
        facility, reporter, investigator, assignee, incident, action = (
            setup_incident_with_action())
        assert incident["status"] == "ACTIONS_ASSIGNED"

        completed = validate_success(
            api_client.complete_corrective_action(
                action["id"], make_operator_headers(assignee["id"])),
            expected_status=200)
        assert completed["status"] == "COMPLETED"

        # COMPLETED is not VERIFIED: the pending count is still nonzero
        resp = api_client.close_incident(incident["id"], CO)
        validate_error(resp, ApiErrorId.ERR_ACTIONS_OPEN, expected_status=409)

    def test_incident_close_succeeds_after_verify(self):
        """PRD section 3.6: "Verification belongs to the incident's
        investigator: acting as an `Operator` whose `X-User-ID` matches the
        incident's `investigator_employee_id`, they move a `COMPLETED` action
        to `VERIFIED`, or reject it back to `OPEN`, which increments the
        pending count again."
        PRD section 3.6: "From `ACTIONS_ASSIGNED`, close requires every action
        `VERIFIED`; a nonzero `pending_action_count` is rejected with
        `ERR_ACTIONS_OPEN` (409)."

        Design: Difficulty/cross_entity_state_dependency/incident_close_requires_actions_verified
        """
        facility, reporter, investigator, assignee, incident, action = (
            setup_incident_with_action())
        validate_success(
            api_client.complete_corrective_action(
                action["id"], make_operator_headers(assignee["id"])),
            expected_status=200)
        verified = validate_success(
            api_client.verify_corrective_action(
                action["id"], make_operator_headers(investigator["id"])),
            expected_status=200)
        assert verified["status"] == "VERIFIED"

        # the gate reads CorrectiveAction state: with all actions VERIFIED the
        # identical close now succeeds
        closed = validate_success(api_client.close_incident(incident["id"], CO),
                                  expected_status=200)
        assert closed["status"] == "CLOSED"
        assert_incident(closed)


class TestPendingCountConservation:

    def test_pending_count_drops_on_complete(self):
        """PRD section 3.6: "The action opens as `OPEN`; the incident's
        `pending_action_count` — its tally of actions in any status other than
        `VERIFIED` — increments, and when the incident stood
        `UNDER_INVESTIGATION`, its first action moves it automatically to
        `ACTIONS_ASSIGNED`."
        PRD section 3.6: "The assignee, acting in the `Operator` role with an
        `X-User-ID` matching the action's `assignee_employee_id` (`ERR_FORBIDDEN`
        otherwise), completes an `OPEN` action, moving it to `COMPLETED` and
        decrementing the pending count."

        Design: Difficulty/compensating_invariant/corrective_action_pending_count_conservation
        """
        facility, reporter, investigator, assignee = setup_incident_cast()
        assignee2 = create_employee(facility["id"], "Andy Two")
        incident = create_under_investigation_incident(
            facility["id"], reporter["id"], investigator["id"],
            description="packing gland leak")
        action1 = create_open_action(incident["id"], assignee["id"],
                                     description="replace packing",
                                     due_at="2026-08-20T00:00:00Z")
        create_open_action(incident["id"], assignee2["id"],
                           description="torque check",
                           due_at="2026-08-21T00:00:00Z")
        baseline = get_incident(incident["id"])
        assert baseline["pending_action_count"] == 2
        assert baseline["status"] == "ACTIONS_ASSIGNED"

        completed = validate_success(
            api_client.complete_corrective_action(
                action1["id"], make_operator_headers(assignee["id"])),
            expected_status=200)
        assert completed["status"] == "COMPLETED"
        after = get_incident(incident["id"])
        assert after["pending_action_count"] == 1

    def test_pending_count_restored_after_reject(self):
        """PRD section 3.6: "Verification belongs to the incident's
        investigator: acting as an `Operator` whose `X-User-ID` matches the
        incident's `investigator_employee_id`, they move a `COMPLETED` action
        to `VERIFIED`, or reject it back to `OPEN`, which increments the
        pending count again."

        Design: Difficulty/compensating_invariant/corrective_action_pending_count_conservation
        """
        facility, reporter, investigator, assignee = setup_incident_cast()
        assignee2 = create_employee(facility["id"], "Andy Two")
        incident = create_under_investigation_incident(
            facility["id"], reporter["id"], investigator["id"],
            description="packing gland leak")
        action1 = create_open_action(incident["id"], assignee["id"],
                                     description="replace packing",
                                     due_at="2026-08-20T00:00:00Z")
        create_open_action(incident["id"], assignee2["id"],
                           description="torque check",
                           due_at="2026-08-21T00:00:00Z")
        assert get_incident(incident["id"])["pending_action_count"] == 2

        validate_success(
            api_client.complete_corrective_action(
                action1["id"], make_operator_headers(assignee["id"])),
            expected_status=200)
        assert get_incident(incident["id"])["pending_action_count"] == 1

        # the reject is the compensating action: the conserved count returns
        rejected = validate_success(
            api_client.reject_corrective_action(
                action1["id"], make_operator_headers(investigator["id"])),
            expected_status=200)
        assert rejected["status"] == "OPEN"
        after = get_incident(incident["id"])
        assert after["pending_action_count"] == 2


class TestSegregationOfDuties:

    def test_investigator_equals_reporter_rejected(self):
        """PRD section 3.6: "The `investigator_employee_id` must reference an
        `ACTIVE` employee of the same facility (`ERR_NOT_FOUND` when unknown,
        `ERR_CROSS_FACILITY_REFERENCE` when of another facility) and must
        differ from the reporter, a segregation-of-duties pin enforced as
        `ERR_INVESTIGATOR_IS_REPORTER` (422)."
        PRD section 3.6: "Assigning from `REOPENED` replaces whatever
        investigator the record previously held; the field stays null until the
        first assignment."

        Design: Corner/validations/investigator_equals_reporter_rejected
        """
        facility, reporter, investigator, assignee = setup_incident_cast()
        incident = create_reported_incident(
            facility["id"], reporter["id"], severity="NEAR_MISS",
            description="odor near valve")
        resp = api_client.assign_investigator(
            incident["id"], {"investigator_employee_id": reporter["id"]}, CO)
        validate_error(resp, ApiErrorId.ERR_INVESTIGATOR_IS_REPORTER,
                       expected_status=422)
        after = get_incident(incident["id"])
        assert after["status"] == "REPORTED"
        assert after.get("investigator_employee_id") is None

    def test_verifier_equals_completer_rejected(self):
        """PRD section 3.6: "The second segregation pin forbids
        self-verification: when the investigator and the assignee are the same
        employee, a verify attempt is refused with
        `ERR_VERIFIER_IS_COMPLETER` (422)."

        Design: Corner/validations/verifier_equals_completer_rejected
        """
        facility, reporter, investigator, assignee = setup_incident_cast()
        incident = create_under_investigation_incident(
            facility["id"], reporter["id"], investigator["id"],
            description="gasket leak")
        # the investigator is also the action's assignee
        action = create_open_action(incident["id"], investigator["id"],
                                    description="replace gasket")
        completed = validate_success(
            api_client.complete_corrective_action(
                action["id"], make_operator_headers(investigator["id"])),
            expected_status=200)
        assert completed["status"] == "COMPLETED"

        resp = api_client.verify_corrective_action(
            action["id"], make_operator_headers(investigator["id"]))
        validate_error(resp, ApiErrorId.ERR_VERIFIER_IS_COMPLETER,
                       expected_status=422)
        after = validate_success(
            api_client.get_corrective_action(action["id"], CO),
            expected_status=200)
        assert after["status"] == "COMPLETED"
