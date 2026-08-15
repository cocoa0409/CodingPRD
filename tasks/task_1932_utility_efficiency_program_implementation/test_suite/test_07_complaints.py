"""Complaints: branching state machine, severity gate, terminal lockdown,
and the rolling 90-day recency counter."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_complaint,
    create_contractor_with_cert,
    create_customer,
    validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


def _customer_and_contractor(api):
    bundle = create_contractor_with_cert(approve=False)
    customer = create_customer()
    return customer, bundle["contractor"]


class TestComplaintBranchingStates:
    def test_open_to_escalated_to_resolved(self, api, pm_headers):
        """PRD 3.8: "Escalation is reserved for serious matters: moving a
        complaint `OPEN` → `ESCALATED` or `IN_REVIEW` → `ESCALATED` requires a
        `severity` of `HIGH` or `CRITICAL`" and "Resolution is terminal and is
        reachable from review (`IN_REVIEW` → `RESOLVED`) or after escalation
        (`ESCALATED` → `RESOLVED`)."

        Design: Difficulty/non_linear_state_machine/complaint_branching_states
        """
        customer, contractor = _customer_and_contractor(api)
        complaint = create_complaint(customer["id"], contractor["id"],
                                     severity="HIGH", description="Bad install")
        assert complaint["status"] == "OPEN"
        escalated = validate_success(
            api.escalate_complaint(complaint["id"], pm_headers), 200)
        assert escalated["status"] == "ESCALATED"
        resolved = validate_success(
            api.resolve_complaint(complaint["id"], pm_headers), 200)
        assert resolved["status"] == "RESOLVED"

    def test_open_to_in_review_to_resolved(self, api, pm_headers):
        """PRD 3.8: "A `ProgramManager` starts review, moving a complaint
        `OPEN` → `IN_REVIEW`. Resolution is terminal and is reachable from
        review (`IN_REVIEW` → `RESOLVED`) or after escalation (`ESCALATED` →
        `RESOLVED`)."

        Design: Difficulty/non_linear_state_machine/complaint_branching_states
        """
        customer, contractor = _customer_and_contractor(api)
        complaint = create_complaint(customer["id"], contractor["id"],
                                     severity="LOW", description="minor")
        in_review = validate_success(
            api.start_review_complaint(complaint["id"], pm_headers), 200)
        assert in_review["status"] == "IN_REVIEW"
        resolved = validate_success(
            api.resolve_complaint(complaint["id"], pm_headers), 200)
        assert resolved["status"] == "RESOLVED"


class TestEscalateSeverityGate:
    def test_escalate_low_severity_rejected(self, api, pm_headers):
        """PRD 3.8: "moving a complaint `OPEN` → `ESCALATED` or `IN_REVIEW` →
        `ESCALATED` requires a `severity` of `HIGH` or `CRITICAL`, and an
        escalation attempted on a lower-severity complaint is refused with
        `ERR_SEVERITY_TOO_LOW`."

        Design: Corner/state_machines/escalate_low_severity_rejected
        """
        customer, contractor = _customer_and_contractor(api)
        complaint = create_complaint(customer["id"], contractor["id"],
                                     category="BILLING", severity="LOW",
                                     description="minor")
        resp = api.escalate_complaint(complaint["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_SEVERITY_TOO_LOW)


class TestTerminalStateLockdown:
    def test_terminal_state_lockdown_complaint(self, api, pm_headers):
        """PRD 3.8: "Resolution is terminal".
        PRD 2.6: "then state-transition validity — a transition requested from
        a state that does not permit it is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."
        Escalation is defined only from OPEN or IN_REVIEW; from RESOLVED the
        transition does not exist.

        Design: Corner/state_machines/terminal_state_lockdown_complaint
        """
        customer, contractor = _customer_and_contractor(api)
        complaint = create_complaint(customer["id"], contractor["id"],
                                     severity="HIGH", description="x")
        validate_success(api.start_review_complaint(complaint["id"], pm_headers), 200)
        validate_success(api.resolve_complaint(complaint["id"], pm_headers), 200)
        resp = api.escalate_complaint(complaint["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestComplaintRecencyWindow:
    def test_complaint_recency_window_drops_old(self, api, pm_headers):
        """PRD 3.8: "it counts the contractor's complaints in `OPEN`,
        `IN_REVIEW`, or `ESCALATED` whose `created_at` lies within the 90 days
        preceding the current logical clock. Resolving a complaint drops it out
        of the count immediately".

        Design: Corner/calculations/complaint_recency_window_drops_old
        """
        customer, contractor = _customer_and_contractor(api)
        complaint = create_complaint(customer["id"], contractor["id"],
                                     severity="MEDIUM", description="x")
        after_create = validate_success(api.get_contractor(contractor["id"], pm_headers))
        assert after_create["complaint_count_90d"] == 1
        validate_success(api.start_review_complaint(complaint["id"], pm_headers), 200)
        validate_success(api.resolve_complaint(complaint["id"], pm_headers), 200)
        after_resolve = validate_success(api.get_contractor(contractor["id"], pm_headers))
        assert after_resolve["complaint_count_90d"] == 0
