"""Investigations, root-cause discipline, and corrective-action lifecycle."""
from test_helpers import (
    ApiErrorId,
    assert_corrective_action,
    assert_investigation,
    classify_case,
    create_case,
    create_classified_case,
    create_corrective_action,
    open_investigation,
    reopen_investigation_as_lead,
    setup_org,
    submit_root_cause,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OFFICER
from test_helpers.test_users import make_investigating_supervisor_headers


class TestInvestigationReopenCycle:
    def test_investigation_reopen_cycle(self, api):
        """PRD §3.4: "If the findings need rework, the same recorded lead may
        reopen the investigation, returning it to `OPEN`; the previously
        submitted `root_cause` and `contributing_factors` are retained —
        clearing them is not permitted."
        PRD §3.4: "Closure belongs to a `SafetyOfficer` and proceeds only from
        `ROOT_CAUSE_SUBMITTED`."

        Design: Corner/state_machines/investigation_reopen_cycle
        """
        _, establishment, employee = setup_org(fein="23-0000011",
                                               site_name="Site IR")
        case = create_classified_case(establishment["id"], employee["id"],
                                      "2026-07-30T10:00:00Z")
        investigation = open_investigation(case["id"], "sup-200")
        submitted = submit_root_cause(investigation["id"], "sup-200",
                                      root_cause="PROCESS",
                                      contributing_factors="No JHA")
        assert submitted["status"] == "ROOT_CAUSE_SUBMITTED"

        reopened = reopen_investigation_as_lead(investigation["id"], "sup-200")
        assert_investigation(reopened)
        assert reopened["status"] == "OPEN"
        assert reopened["root_cause"] == "PROCESS", (
            "Reopen retains the previously submitted root cause")
        assert reopened["contributing_factors"] == "No JHA"

        resp = api.close_investigation(investigation["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_root_cause_submission_by_non_lead_rejected(self, api):
        """PRD §3.4: "A submission from anyone other than the recorded
        `lead_supervisor_id` is rejected with `ERR_NOT_INVESTIGATION_LEAD`."

        Design: Corner/validations/not_investigation_lead_cannot_submit_root_cause
        """
        _, establishment, employee = setup_org(fein="05-0000024",
                                               site_name="Lead Site")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-01T10:00:00Z",
            clock_iso="2026-08-01T12:00:00Z")
        investigation = open_investigation(case["id"], "sup-A")

        resp = api.submit_root_cause(
            investigation["id"],
            {"root_cause": "TRAINING", "contributing_factors": "No training"},
            make_investigating_supervisor_headers("sup-B"))
        validate_error(resp, ApiErrorId.ERR_NOT_INVESTIGATION_LEAD)


class TestCorrectiveActionLifecycle:
    def _recordable_case(self, fein):
        _, establishment, employee = setup_org(fein=fein, site_name="CA Site")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-07-30T10:00:00Z")
        return establishment, case

    def test_verify_requires_completed_state(self, api):
        """PRD §3.5: "The action moves to `COMPLETED` with `completed_at`
        stamped and `completed_by` recorded. Verification is a second,
        segregated duty: the verifying operator must differ from the operator
        recorded in `completed_by`"
        PRD §2.9: "Fourth, state admissibility: the target resource must
        currently sit in a state from which the requested transition exists,
        failing with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/corrective_action_verify_requires_completed_state
        """
        establishment, case = self._recordable_case("45-0000013")
        action = create_corrective_action(establishment["id"],
                                          case_id=case["id"],
                                          assigned_to="op-7")
        assert action["status"] == "OPEN"

        resp = api.verify_corrective_action(action["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_corrective_action_linkage_xor_enforced(self, api):
        """PRD §3.5: "Every action links to exactly one trigger: a `case_id`
        when it arises from an incident, or a `citation_id` when it arises
        from a citation — supplying both or neither is rejected with
        `ERR_LINKAGE_XOR`."

        Design: Corner/entities/corrective_action_linkage_xor_enforced
        """
        _, establishment, employee = setup_org(fein="66-0000006",
                                               site_name="Site X")
        create_case(establishment["id"], employee["id"],
                    "2026-07-30T10:00:00Z", description="X")
        resp = api.create_corrective_action(
            {"establishment_id": establishment["id"],
             "description": "No link", "assigned_to": "op-1",
             "due_date": "2026-09-01", "priority": "LOW"},
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_LINKAGE_XOR)

    def test_complete_with_wrong_operator_rejected(self, api):
        """PRD §3.5: "Completion is recorded by a `SafetyOfficer` submitting
        `completed_by`, which must match the action's `assigned_to` — a
        mismatch is rejected with `ERR_NOT_ASSIGNEE`."

        Design: Corner/errors/error_not_assignee_on_complete
        """
        _, establishment, employee = setup_org(fein="11-0000030",
                                               site_name="NA Site")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-01T10:00:00Z",
            clock_iso="2026-08-01T12:00:00Z")
        action = create_corrective_action(establishment["id"],
                                          case_id=case["id"],
                                          assigned_to="op-A",
                                          description="Fix")
        assert_corrective_action(action)

        resp = api.complete_corrective_action(
            action["id"], {"completed_by": "op-B"}, OFFICER)
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNEE)
