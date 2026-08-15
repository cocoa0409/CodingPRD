"""Role-based access control and the user-context header tier."""
from test_helpers import (
    AUDITOR,
    MANAGER,
    OFFICER,
    ApiErrorId,
    api_client,
    create_account_payload,
    open_account,
    submit_document,
    title_change_payload,
    validate_error,
)


class TestRoleAuthorization:

    def test_auditor_cannot_create_account(self):
        """PRD section 2.1: "`Auditor` is a read-only oversight role limited
        to retrieval endpoints."
        PRD section 2.1: "An attempt to perform an action outside the
        caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/auditor_cannot_create_account
        """
        resp = api_client.create_account(
            create_account_payload(primary_owner_name="Aud A",
                                   owner_tax_id="R1",
                                   opening_deposit_cents=1000),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_officer_cannot_review_documents(self):
        """PRD section 3.2: "Review is a manager's act."
        PRD section 2.1: "An attempt to perform an action outside the
        caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/officer_cannot_review_documents
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Rev R", owner_tax_id="R2")
        doc = submit_document(acct["id"], "SIGNATURE_CARD", "SC-R2")

        resp = api_client.review_document(doc["id"], {"decision": "VERIFIED"},
                                          OFFICER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_manager_cannot_file_title_change(self):
        """PRD section 3.3: "An `OpsOfficer` files a title change request
        naming the `requested_ownership_type` — which must differ from the
        account's current `ownership_type`, failing shape validation with
        `ERR_INVALID_REQUEST` otherwise — plus a `pod_beneficiary_name`
        when, and only when, the requested type is `POD`."
        PRD section 2.1: "An attempt to perform an action outside the
        caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/manager_cannot_file_title_change
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Mgr M", owner_tax_id="R3")

        resp = api_client.file_title_change(
            acct["id"],
            title_change_payload("JOINT", acct["version"]),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestUserContextHeaders:

    def test_create_account_missing_auth_header_unauthenticated(self):
        """PRD section 2.1: "Every request must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`,
        declaring the caller's operational capacity. A request missing
        either header, or naming a role the system does not declare, is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."
        PRD section 2.10: "Ordering decides which error a doubly-invalid
        request reports. A missing header rejects before any role check
        runs".

        Design: Corner/rbac/create_account_missing_auth_header_unauthenticated
        """
        resp = api_client.create_account(
            create_account_payload(primary_owner_name="NoH N",
                                   owner_tax_id="R4",
                                   opening_deposit_cents=1000),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
