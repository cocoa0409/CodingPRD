"""Role-based access control (PRD §2.1, §2.9, §4) and the immediate-consistency
guarantee (PRD §2.2)."""
from test_helpers import (
    ApiErrorId,
    authorize,
    create_notice,
    make_account,
    make_account_holder_headers,
    make_opted_in_account,
    make_posted_fee_scenario,
    make_program,
    open_batch,
    set_clock,
    submit_waiver,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, TELLER


class TestTellerCannotSuspendProgram:
    def test_program_lifecycle_is_program_admin_only(self, api):
        """PRD §2.1: "Access to every operation is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: POST /v1/programs/{id}/suspend is authorized for ProgramAdmin.

        Design: Corner/rbac/teller_cannot_suspend_program_returns_forbidden
        """
        program = make_program(name="OD-R1")
        resp = api.suspend_program(program["id"], TELLER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_program_status(api, program["id"]) == "ACTIVE"


class TestAccountHolderCannotSealBatch:
    def test_batch_lifecycle_is_operations_clerk_only(self, api):
        """PRD §2.1: "Access to every operation is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: POST /v1/batches/{id}/seal is authorized for OperationsClerk.

        Design: Corner/rbac/accountholder_cannot_seal_batch_returns_forbidden
        """
        program = make_program(name="OD-R2")
        account = make_account(program["id"], holder_name="H R2")
        batch = open_batch(program["id"], "2026-08-03")
        holder = make_account_holder_headers(account["id"])
        resp = api.seal_batch(batch["id"], holder)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestTellerCannotActivateNotice:
    def test_notice_activation_is_compliance_only(self, api):
        """PRD §2.9: "Program-change notices split issuance from activation by
        role: a `ProgramAdmin` drafts and issues a notice, but only a
        `ComplianceOfficer` may activate it once its disclosure window has
        elapsed."
        PRD §2.1: "an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/teller_cannot_activate_notice_returns_forbidden
        """
        program = make_program(name="OD-R3")
        notice = create_notice(program["id"], parameter="DAILY_CAP_CENTS",
                               new_value="11000")
        set_clock("2026-08-03T09:00:00Z")
        validate_success(api.issue_notice(notice["id"], ADMIN))

        resp = api.activate_notice(notice["id"], TELLER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestAccountHolderCannotApproveWaiver:
    def test_approval_roles_exclude_the_account_holder(self, api):
        """PRD §2.1: "Access to every operation is restricted by role; an
        attempt to perform an action outside the caller's designated role is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: POST /v1/fee-waiver-requests/{id}/approve is authorized for
        Supervisor, Manager, ComplianceOfficer.

        Design: Corner/rbac/accountholder_cannot_approve_waiver_returns_forbidden
        """
        ctx = make_posted_fee_scenario()
        account, fee = ctx["account"], ctx["fee"]
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="FIRST_TIME", as_holder=True)
        holder = make_account_holder_headers(account["id"])
        resp = api.approve_fee_waiver_request(request["id"], holder)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestAccountHolderCannotTransactForOtherAccount:
    def test_holder_identity_must_match_target_account(self, api):
        """PRD §2.1: "When `X-User-Role` is `AccountHolder`, `X-User-ID` is the
        `id` of the acting `DepositAccount`; ownership checks on any resource
        that references a `DepositAccount` compare the resource's account
        reference to `X-User-ID`, and a mismatch is rejected with
        `ERR_ACCOUNT_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/accountholder_cannot_transact_for_other_account
        """
        program = make_program(name="OD-R5")
        account1 = make_account(program["id"], holder_name="H One")
        account2 = make_account(program["id"], holder_name="H Two")

        resp = api.create_transaction(
            {"account_id": account1["id"], "type": "DEBIT_ONE_TIME",
             "amount_cents": 100},
            make_account_holder_headers(account2["id"]))
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_OWNERSHIP_MISMATCH)


class TestImmediateConsistency:
    def test_mutations_return_post_mutation_resource_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        program = make_program(name="OD-CON1")
        account, election = make_opted_in_account(program["id"],
                                                  holder_name="H CON1")
        holder = make_account_holder_headers(account["id"])
        # The revoke response itself shows the post-mutation state.
        revoked = validate_success(
            api.revoke_opt_in_election(election["id"], holder))
        assert revoked["status"] == "REVOKED"
        assert revoked["version"] == 2

        batch = open_batch(program["id"], "2026-08-03")
        authorize(account["id"], "CREDIT_DEPOSIT", 700)
        # The seal response itself carries the computed counters.
        seal = validate_success(api.seal_batch(batch["id"], CLERK))
        assert seal["status"] == "SEALED"
        assert seal["items_posted_count"] == 1


def get_program_status(api, program_id):
    return validate_success(api.get_program(program_id, ADMIN))["status"]
