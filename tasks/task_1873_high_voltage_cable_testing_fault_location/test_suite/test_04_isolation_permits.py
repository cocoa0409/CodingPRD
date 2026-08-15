"""Isolation permit safety: uniqueness, two-person rule, release gates
(PRD §3.4, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    SAFETY_OFFICER_1_HEADERS,
    SAFETY_OFFICER_2_HEADERS,
    SAFETY_OFFICER_3_HEADERS,
    make_safety_officer_headers,
    validate_success,
    validate_error,
    setup_planned_job,
    setup_job_in_evaluation,
    create_permit,
    issue_permit,
    verify_grounding,
    get_circuit,
    get_job,
)

PLANNER = TEST_USERS["network_planner_headers"]
SUPERVISOR = TEST_USERS["test_supervisor_headers"]


class TestPermitUniqueness:
    def test_second_open_permit_rejected(self, api):
        """PRD §3.4: "At most one permit that has not reached `RELEASED` may
        exist per job, and that uniqueness check runs after the job-state
        check; a second open permit is rejected with `ERR_PERMIT_EXISTS`."

        Design: Corner/validations/permit_exists_rejected
        """
        ctx = setup_planned_job(circuit_ref="CKT-V9")
        create_permit(ctx["job"]["id"])
        resp = api.create_permit(
            {
                "test_job_id": ctx["job"]["id"],
                "isolation_points": ["SW-X"],
                "ground_count": 1,
            },
            make_safety_officer_headers("so-4"),
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_EXISTS)


class TestSegregationOfDuties:
    def test_issuer_cannot_verify_own_grounding(self, api):
        """PRD §2.9: "The operator who verifies grounding must be a different
        `X-User-ID` than the operator who issued the permit, and the operator
        who releases the permit must be a different `X-User-ID` than the
        operator who verified grounding. Either violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

        Design: Corner/validations/segregation_verify_self_rejected
        """
        ctx = setup_planned_job(circuit_ref="CKT-V15")
        permit = issue_permit(create_permit(ctx["job"]["id"])["id"])

        self_verify = api.verify_grounding(permit["id"], SAFETY_OFFICER_1_HEADERS)
        validate_error(self_verify, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        still_issued = validate_success(api.get_permit(permit["id"], SAFETY_OFFICER_1_HEADERS))
        assert still_issued["status"] == "ISSUED"

        verified = verify_grounding(permit["id"])
        assert verified["status"] == "GROUNDING_VERIFIED"
        assert verified["issued_by_user_id"] == "so-1"
        assert verified["grounding_verified_by_user_id"] == "so-2"

    def test_planner_cannot_verify_grounding(self, api):
        """PRD §4: "| POST | /cable-diagnostics/isolation-permits/{id}/verify-grounding | Independent grounding verification; verifier must differ from issuer | SafetyOfficer |"
        — a NetworkPlanner is not listed for the endpoint.
        PRD §2.1: "Once authenticated, the role must be among the roles
        allowed for the specific endpoint; otherwise the request is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/planner_cannot_verify_grounding
        """
        ctx = setup_planned_job(circuit_ref="CKT-R3")
        permit = issue_permit(create_permit(ctx["job"]["id"])["id"])
        resp = api.verify_grounding(permit["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        still_issued = validate_success(api.get_permit(permit["id"], SAFETY_OFFICER_1_HEADERS))
        assert still_issued["status"] == "ISSUED"


class TestReleaseAndCompletionGates:
    def test_release_segregation_and_completion_gate(self, api):
        """PRD §3.4: "Release comes at the end of testing and is doubly gated:
        the job must already be in `EVALUATION` — checked first, with
        `ERR_INVALID_STATE` if not — and the releasing officer must differ
        from the grounding verifier, with a same-person attempt rejected as
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.3: "Completion of an `EVALUATION` job is gated on the job's
        isolation permit having reached `RELEASED` — completing earlier is
        rejected with `ERR_PERMIT_NOT_RELEASED` — and lands the job in
        `COMPLETED`."

        Design: Corner/validations/permit_release_segregation_and_complete_gate
        """
        ctx = setup_job_in_evaluation(circuit_ref="CKT-V23")
        job_id = ctx["job"]["id"]
        permit_id = ctx["permit"]["id"]

        early_complete = api.complete_job(job_id, SUPERVISOR)
        validate_error(early_complete, ApiErrorId.ERR_PERMIT_NOT_RELEASED)

        verifier_release = api.release_permit(permit_id, SAFETY_OFFICER_2_HEADERS)
        validate_error(verifier_release, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        released = validate_success(api.release_permit(permit_id, SAFETY_OFFICER_3_HEADERS))
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "so-3"
        assert get_circuit(ctx["circuit"]["id"])["status"] == "RESTORING", (
            "release moves the circuit TEST_COMPLETE → RESTORING (PRD §3.4)"
        )

        completed = validate_success(api.complete_job(job_id, SUPERVISOR))
        assert completed["status"] == "COMPLETED"
