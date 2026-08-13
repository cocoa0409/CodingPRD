"""Visit day lifecycle: dual state dimensions, workload forward/audit
divergence, schedule/cancel conservation, no-show sweep, and the incident
escalation cascade."""
from test_helpers import (
    api_client,
    assert_instants_equal,
    complete_visit_ok,
    create_request_ok,
    file_incident_ok,
    get_animal,
    get_certification,
    get_team,
    get_visit,
    get_visit_request,
    offer_request_ok,
    accept_request_ok,
    run_sweeps,
    schedule_visit_ok,
    set_clock,
    setup_certified_team_at_facility,
    triage_incident_ok,
    make_facility_coordinator_headers,
    make_handler_headers,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestWorkloadForwardVsAudit:
    def _ctx_with_scheduled_visit(self):
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H Two", "team_name": "Mog Team",
                         "species": "CAT", "animal_name": "Mog", "breed": "Ragdoll"},
            facility_kwargs={"name": "School B", "allowed_species": ["DOG", "CAT"]},
        )
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        return ctx, visit

    def test_scheduled_visit_counts_forward_only(self):
        """PRD §3.7: "The forward-looking figure `forward_workload_minutes` looks across the window from seven days before now to seven days after now — the future bound excluded — and counts the animal's teams' visits in `SCHEDULED` or `IN_PROGRESS` at their scheduled minutes plus visits in `COMPLETED` at their `actual_minutes`. The audit figure `audit_workload_minutes` looks across the window from seven days before now through now inclusive and counts only `COMPLETED` visits at their `actual_minutes`. Visits `CANCELLED` or `NO_SHOW` are excluded from both, and both figures are recomputed at booking, acceptance, check-out, cancellation, and no-show — so a heavily booked but untested animal shows a forward figure well above its audit figure."

        Design: Difficulty/dual_variant_calc/workload_forward_vs_audit_divergence
        """
        ctx, _visit = self._ctx_with_scheduled_visit()
        animal = get_animal(ctx["animal"]["id"])
        assert animal["forward_workload_minutes"] == 60, (
            "FORWARD_LOOKING counts the SCHEDULED visit at its scheduled minutes"
        )
        assert animal["audit_workload_minutes"] == 0, (
            "AUDIT counts only COMPLETED visits; nothing has completed yet"
        )

    def test_completed_visit_counts_in_both_variants(self):
        """PRD §3.7: "The forward-looking figure `forward_workload_minutes` looks across the window from seven days before now to seven days after now — the future bound excluded — and counts the animal's teams' visits in `SCHEDULED` or `IN_PROGRESS` at their scheduled minutes plus visits in `COMPLETED` at their `actual_minutes`. The audit figure `audit_workload_minutes` looks across the window from seven days before now through now inclusive and counts only `COMPLETED` visits at their `actual_minutes`. Visits `CANCELLED` or `NO_SHOW` are excluded from both, and both figures are recomputed at booking, acceptance, check-out, cancellation, and no-show — so a heavily booked but untested animal shows a forward figure well above its audit figure."

        Design: Difficulty/dual_variant_calc/workload_forward_vs_audit_divergence
        """
        ctx, visit = self._ctx_with_scheduled_visit()
        complete_visit_ok(visit["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        animal = get_animal(ctx["animal"]["id"])
        # COMPLETED at 60 actual minutes: counted by both variants.
        assert animal["forward_workload_minutes"] == 60
        assert animal["audit_workload_minutes"] == 60


class TestScheduleCancelWorkloadConservation:
    def test_scheduling_increments_forward_workload(self):
        """PRD §3.7: "A visit that clears the chain starts `SCHEDULED` and `UNVERIFIED`, increments the team's `version` by one, and raises the animal's `forward_workload_minutes` by the scheduled minutes."

        Design: Difficulty/compensating_invariant/schedule_cancel_workload_conservation
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H V2", "team_name": "TV2"},
            facility_kwargs={"name": "School S"},
        )
        before = get_animal(ctx["animal"]["id"])
        assert before["forward_workload_minutes"] == 0
        schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        after = get_animal(ctx["animal"]["id"])
        assert after["forward_workload_minutes"] == 60, (
            "Scheduling must increment by the visit's scheduled minutes"
        )

    def test_cancellation_returns_workload_to_baseline(self):
        """PRD §3.7: "The animal's `forward_workload_minutes` drops by the visit's scheduled minutes, compensating the scheduling increment, and a request-backed visit returns its request `ACCEPTED → OPEN` with offer fields cleared."

        Design: Difficulty/compensating_invariant/schedule_cancel_workload_conservation
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H V2c", "team_name": "TV2c"},
            facility_kwargs={"name": "School Sc"},
        )
        baseline = get_animal(ctx["animal"]["id"])["forward_workload_minutes"]
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        validate_success(
            api_client.cancel_visit(visit["id"], {"reason": "handler conflict"}, ADMIN)
        )
        restored = get_animal(ctx["animal"]["id"])
        assert restored["forward_workload_minutes"] == baseline, (
            "Cancellation decrements by exactly the scheduling increment; no drift"
        )


class TestVisitParallelDimensions:
    def _completed_visit(self):
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H P", "team_name": "TP"},
            facility_kwargs={"name": "School G"},
        )
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        return ctx, visit

    def test_lifecycle_moves_leave_verification_untouched(self):
        """PRD §3.8: "Verification status moves only while the visit stands `COMPLETED`, and starts at `UNVERIFIED`."
        PRD §3.7: "A visit that clears the chain starts `SCHEDULED` and `UNVERIFIED`, increments the team's `version` by one, and raises the animal's `forward_workload_minutes` by the scheduled minutes."

        Design: Difficulty/non_linear_state_machine/visit_parallel_dimensions
        """
        ctx, visit = self._completed_visit()
        assert visit["lifecycle_status"] == "SCHEDULED"
        assert visit["verification_status"] == "UNVERIFIED"
        in_progress = validate_success(
            _check_in_at(visit["id"], ctx["handler"]["id"], "2026-08-03T10:00:00Z")
        )
        assert in_progress["lifecycle_status"] == "IN_PROGRESS"
        assert in_progress["verification_status"] == "UNVERIFIED", (
            "The lifecycle move must leave verification untouched"
        )
        completed = validate_success(
            _check_out_at(visit["id"], ctx["handler"]["id"], "2026-08-03T11:00:00Z")
        )
        assert completed["lifecycle_status"] == "COMPLETED"
        assert completed["verification_status"] == "UNVERIFIED"

    def test_dispute_and_resolution_leave_lifecycle_untouched(self):
        """PRD §3.8: "When the facility disagrees with the record, the same coordinator instead disputes the completed, still-`UNVERIFIED` visit with a `dispute_reason`, moving verification to `DISPUTED`. Resolution then belongs to a `ComplianceOfficer` acting on a `DISPUTED` visit (otherwise `ERR_VISIT_NOT_DISPUTED`) by supplying `approved_minutes` between zero and the scheduled minutes inclusive (outside that range fails `ERR_INVALID_REQUEST`): the ruling sets `approved_minutes` and `verified_at` and runs the same reversal-then-final reconciliation, except the final credit takes `approved_minutes` in place of the actual minutes — the smallest of `approved_minutes`, the scheduled minutes, and the effective cap, rounded to fifteen-minute units."

        Design: Difficulty/non_linear_state_machine/visit_parallel_dimensions
        """
        ctx, visit = self._completed_visit()
        complete_visit_ok(visit["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        disputed = validate_success(
            api_client.dispute_visit(
                visit["id"], {"dispute_reason": "duration mismatch"},
                make_facility_coordinator_headers(ctx["facility"]["id"]),
            )
        )
        assert disputed["verification_status"] == "DISPUTED"
        assert disputed["lifecycle_status"] == "COMPLETED", (
            "The verification move must leave the lifecycle untouched"
        )
        resolved = validate_success(
            api_client.resolve_dispute(visit["id"], {"approved_minutes": 40}, COMPLIANCE)
        )
        assert resolved["verification_status"] == "VERIFIED"
        assert resolved["lifecycle_status"] == "COMPLETED"
        assert resolved["approved_minutes"] == 40


def _check_in_at(visit_id, handler_id, at):
    set_clock(at)
    return api_client.check_in_visit(visit_id, make_handler_headers(handler_id))


def _check_out_at(visit_id, handler_id, at):
    set_clock(at)
    return api_client.check_out_visit(visit_id, make_handler_headers(handler_id))


class TestNoShowSweep:
    def test_no_show_sweep_reopens_backed_request(self):
        """PRD §3.7: "The no-show sweep handles silent absences: a visit still `SCHEDULED` more than thirty minutes past its `scheduled_end` moves to `NO_SHOW`, the team's `no_show_count` increments by one, the animal's `forward_workload_minutes` drops by the scheduled minutes, and a request-backed visit's request returns `ACCEPTED → OPEN`."
        PRD §3.6: "Requests resolve in four terminal directions. Completion of the backed visit bubbles the request `ACCEPTED → FULFILLED` and stamps `fulfilled_on` with the date. Cancellation or no-show of the backed visit compensates the request `ACCEPTED → OPEN`, clearing the offer fields while the visit keeps its `request_id` linkage. A request still `OPEN` once its `requested_end` has passed is swept to `EXPIRED` with `expired_on` stamped — the raw material of the unmet-demand measure of §3.8. And withdrawal ends the request at `WITHDRAWN`."

        Design: Corner/state_machines/no_show_sweep_reopens_backed_request
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H NS", "team_name": "TNS"},
            facility_kwargs={"name": "School W"},
        )
        request = create_request_ok(ctx["facility"]["id"], "2026-08-03T10:00:00Z",
                                    "2026-08-03T11:00:00Z")
        offer_request_ok(request["id"], ctx["team"]["id"])
        visit = accept_request_ok(request["id"], ctx["handler"]["id"])
        # 2026-08-03T11:31 > scheduled_end 11:00 + 30 minutes; never checked in.
        set_clock("2026-08-03T11:31:00Z")
        sweep = run_sweeps()
        assert sweep["visits_marked_no_show"] == 1
        assert get_visit(visit["id"])["lifecycle_status"] == "NO_SHOW"
        assert get_team(ctx["team"]["id"])["no_show_count"] == 1
        assert get_visit_request(request["id"])["status"] == "OPEN", (
            "The backed request compensates back to OPEN"
        )


class TestIncidentEscalationCascade:
    def _setup_escalation(self):
        """Certified team at facility; a COMPLETED visit (incident target) and an
        ACCEPTED request-backed visit still SCHEDULED (cascade target)."""
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H I", "team_name": "TI"},
            facility_kwargs={"name": "School H", "visits_per_week_cap": 8},
        )
        request = create_request_ok(ctx["facility"]["id"], "2026-08-10T14:00:00Z",
                                    "2026-08-10T15:00:00Z")
        offer_request_ok(request["id"], ctx["team"]["id"])
        v_req = accept_request_ok(request["id"], ctx["handler"]["id"])
        v_done = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                   "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        complete_visit_ok(v_done["id"], ctx["handler"]["id"],
                          "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        incident = file_incident_ok(
            v_done["id"], make_facility_coordinator_headers(ctx["facility"]["id"]),
            severity="HIGH", category="ANIMAL_STRESS",
            description="animal showed sustained stress signals",
        )
        triage_incident_ok(incident["id"], COMPLIANCE)
        set_clock("2026-08-03T12:00:00Z")
        escalated = validate_success(api_client.escalate_incident(incident["id"], COMPLIANCE))
        assert escalated["status"] == "ESCALATED"
        return ctx, request, v_req, incident

    def test_escalation_holds_animal_and_suspends_certification(self):
        """PRD §3.9: "Escalation from `UNDER_REVIEW` (otherwise `ERR_INCIDENT_NOT_UNDER_REVIEW`) moves the report to `ESCALATED` and fires the precaution cascade in four hops: the animal of the visit's team, if `ACTIVE`, moves to `WELFARE_HOLD` for fourteen days under `INCIDENT_PRECAUTION`; that team's certification standing `ACTIVE` or `RENEWAL_DUE` moves to `SUSPENDED` with `suspension_reason` `INCIDENT_PRECAUTION`; the team drops to `SUSPENDED` and every `SCHEDULED` visit of the team is cancelled with `cancel_reason` `INCIDENT_PRECAUTION`, the animal's `forward_workload_minutes` decrementing per cancelled visit; and request-backed cancelled visits return their requests to `OPEN`."

        Design: Difficulty/transitive_cascade/incident_escalation_depth4_cascade
        """
        ctx, _request, _v_req, _incident = self._setup_escalation()
        animal = get_animal(ctx["animal"]["id"])
        assert animal["status"] == "WELFARE_HOLD", "Hop 1: precaution hold"
        assert animal["welfare_hold_reason"] == "INCIDENT_PRECAUTION"
        # Escalation ran at 2026-08-03T12:00Z; hold is fixed fourteen days out.
        assert_instants_equal(animal["welfare_hold_until"], "2026-08-17T12:00:00Z")
        cert = get_certification(ctx["certification"]["id"])
        assert cert["status"] == "SUSPENDED", "Hop 2: precaution suspension"
        assert cert["suspension_reason"] == "INCIDENT_PRECAUTION"

    def test_escalation_cancels_visits_and_reopens_requests(self):
        """PRD §3.9: "Escalation from `UNDER_REVIEW` (otherwise `ERR_INCIDENT_NOT_UNDER_REVIEW`) moves the report to `ESCALATED` and fires the precaution cascade in four hops: the animal of the visit's team, if `ACTIVE`, moves to `WELFARE_HOLD` for fourteen days under `INCIDENT_PRECAUTION`; that team's certification standing `ACTIVE` or `RENEWAL_DUE` moves to `SUSPENDED` with `suspension_reason` `INCIDENT_PRECAUTION`; the team drops to `SUSPENDED` and every `SCHEDULED` visit of the team is cancelled with `cancel_reason` `INCIDENT_PRECAUTION`, the animal's `forward_workload_minutes` decrementing per cancelled visit; and request-backed cancelled visits return their requests to `OPEN`."

        Design: Difficulty/transitive_cascade/incident_escalation_depth4_cascade
        """
        ctx, request, v_req, _incident = self._setup_escalation()
        visit = get_visit(v_req["id"])
        assert visit["lifecycle_status"] == "CANCELLED", "Hop 3: SCHEDULED visits cancel"
        assert visit["cancel_reason"] == "INCIDENT_PRECAUTION"
        reopened = get_visit_request(request["id"])
        assert reopened["status"] == "OPEN", (
            "Hop 4: the request-backed visit's request returns to OPEN"
        )
        assert reopened["offered_team_id"] is None, "Offer fields must be cleared"
