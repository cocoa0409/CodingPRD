"""Authentication context, role authorization, entity-backed customer
identity, and bank posture gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_bank,
    create_bank_payload,
    create_batch_payload,
    create_customer,
    begin_onboarding,
    create_agreement,
    implement_agreement,
    make_implementer_headers,
    setup_live_lockbox,
    validate_error,
)

ADMIN = TEST_USERS["bank_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestAuthContext:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "A request with either header missing or malformed is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_user_context_header_rejected
        """
        bank = create_bank()
        resp = api.get_bank(bank["id"], {})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:
    def test_rbac_role_not_permitted_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: agreement activate is authorized for TreasuryActivator only.

        Design: Corner/validations/rbac_role_not_permitted_returns_forbidden
        """
        bank = create_bank()
        customer = create_customer(bank["id"])
        begin_onboarding(bank["id"], customer["id"])
        agreement = create_agreement(bank["id"], customer["id"])
        implement_agreement(bank["id"], customer["id"], agreement["id"])
        # A TreasuryImplementer must not activate an agreement.
        resp = api.activate_agreement(
            bank["id"], customer["id"], agreement["id"],
            agreement["version"] + 1,
            make_implementer_headers("impl-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_auditor_read_only(self, api, auditor_headers):
        """PRD §2.1: "`Auditor` — read-only oversight."
        PRD §4: "POST | `/banks` | Create a Bank | BankOperationsAdmin".

        Design: Corner/rbac/auditor_read_only
        """
        resp = api.create_bank(create_bank_payload(), auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestBankPostureGate:
    def test_bank_not_operating_blocks_value_extending_ops(self, api):
        """PRD §2.5: "Any mutating call that requires an operating bank and
        finds otherwise is rejected with `ERR_BANK_NOT_OPERATING` (HTTP 409);
        bank-level administration itself is exempt from this gate."
        PRD §3.1: "no new batches or image retrieval requests are accepted
        anywhere in the bank while the suspension holds."

        Design: Corner/validations/bank_not_operating_blocks_value_extending_ops
        """
        ws = setup_live_lockbox()
        api.suspend_bank(ws["bank"]["id"], ADMIN)
        resp = api.create_batch(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"],
            create_batch_payload(batch_reference="B-SUSP"),
            TEST_USERS["lockbox_op_headers"])
        validate_error(resp, ApiErrorId.ERR_BANK_NOT_OPERATING)
