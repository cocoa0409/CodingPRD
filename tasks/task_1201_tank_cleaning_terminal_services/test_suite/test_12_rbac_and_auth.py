"""Authentication context, role admission, and entity-backed ownership
(PRD §2.1, §2.11, §3.5, §3.7)."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, build_user_headers,
    create_terminal_payload, create_contractor_payload,
    create_safety_event_payload, create_gas_free_certificate_payload,
    new_ctx, create_job, schedule_job, activate_window_and_take_oos,
    get_job,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]
LAB = TEST_USERS["lab_headers"]
EHS = TEST_USERS["ehs_headers"]


class TestAuthAndRoleAdmission:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        res = api.create_terminal(
            create_terminal_payload(name="NoAuth",
                                    wastewater_daily_capacity_liters=1000),
            headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_existence_check_runs_before_state_check(self, api):
        """PRD §2.11: "Every request is evaluated against a fixed validation pipeline, and the first failing check determines the error returned. Authentication context comes first (§2.1), then role admission and entity-backed ownership, then existence — path identifiers validated left to right before body foreign-key references, a missing one yielding `ERR_NOT_FOUND` (HTTP 404)"

        Design: Corner/validations/existence_beats_state_on_action
        """
        res = api.take_out_of_service(NON_EXISTENT_UUID, OPERATOR)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_safety_event_by_operator_forbidden(self, api):
        """PRD §2.1: "a caller whose role is not admitted — or who fails an ownership check the endpoint requires — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "POST /ops/safety-events | Record a safety event (append-only); recomputes the contractor's score | EHSOfficer"

        Design: Corner/validations/safety_event_by_operator_forbidden
        """
        contractor = validate_success(api.create_contractor(
            create_contractor_payload(), ADMIN), 201)
        res = api.create_safety_event(
            create_safety_event_payload(
                contractor["id"], kind="VIOLATION", severity_weight=1,
                occurred_at="2026-04-01T00:00:00Z"),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_lab_technician_cannot_authorize_discharge(self, api):
        """PRD §2.11: "Authentication context comes first (§2.1), then role admission and entity-backed ownership, then existence"
        PRD §4: "POST /ops/wastewater-batches/{batchId}/authorize | Authorize discharge (limits, daily capacity, segregation of duties vs lab tech) | TerminalOperator"

        Design: Corner/rbac/lab_technician_authorize_forbidden
        """
        # Role admission fires before existence: even a bogus id yields 403.
        res = api.authorize_batch(NON_EXISTENT_UUID, LAB)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_ehs_officer_cannot_issue_gas_free_certificate(self, api):
        """PRD §2.1: "a caller whose role is not admitted — or who fails an ownership check the endpoint requires — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "POST /ops/gas-free-certificates | Issue a gas-free certificate for a job in `GAS_FREE_PENDING` | MarineChemist"

        Design: Corner/rbac/ehs_cannot_issue_gas_free_cert
        """
        res = api.create_gas_free_certificate(
            create_gas_free_certificate_payload(NON_EXISTENT_UUID), EHS)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestEntityBackedOwnership:
    def test_heel_removal_by_other_contractor_forbidden(self, api):
        """PRD §3.5: "The owning `ContractorSupervisor` — the caller's `X-User-ID` must equal the job's `contractor_id`, failing which `ERR_FORBIDDEN_FOR_ROLE` — records the metered pump-out by supplying `metered_liters`"
        PRD §2.1: "When `X-User-Role` is `ContractorSupervisor`, `X-User-ID` is the `id` of the acting Contractor; ownership checks on any resource that references a contractor — cleaning jobs, waste profiles, waste shipments, entry permits, and repair orders via their denormalized job — compare the resource's contractor foreign key to `X-User-ID`."

        Design: Corner/rbac/contractor_ownership_enforced_on_heel_removal
        """
        ctx = new_ctx()
        other = validate_success(api.create_contractor(
            create_contractor_payload(company_name="B-Co"), ADMIN), 201)
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        schedule_job(ctx)
        activate_window_and_take_oos(ctx)

        res = api.record_heel_removal(
            ctx["job"]["id"], {"metered_liters": 100},
            build_user_headers(other["id"], "ContractorSupervisor"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_job(ctx)["status"] == "TANK_OOS"
