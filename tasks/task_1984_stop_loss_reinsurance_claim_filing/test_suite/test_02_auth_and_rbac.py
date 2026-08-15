"""Authentication and role-based access control."""
from test_helpers import (
    ACCOUNTANT,
    ANONYMOUS_HEADERS,
    EXAMINER,
    REVIEWER,
    ApiErrorId,
    create_claim,
    create_member,
    create_plan,
    validate_error,
)


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside this list, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/unauthenticated_request_rejected
        """
        resp = api.list_plans(ANONYMOUS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenials:
    def test_claims_examiner_cannot_create_plan(self, api):
        """PRD §2.1: "A well-authenticated request whose role is not
        permitted to invoke the endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: "| POST | `/stop-loss/plans` | Create a self-funded plan |
        PlanAdministrator |"

        Design: Corner/errors/forbidden_role_rejected
        """
        resp = api.create_plan(
            {"plan_name": "Bad", "sponsor_tax_id": "00-0000000"}, EXAMINER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_carrier_reviewer_cannot_create_plan(self, api):
        """PRD §2.1: "A well-authenticated request whose role is not
        permitted to invoke the endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: "| POST | `/stop-loss/plans` | Create a self-funded plan |
        PlanAdministrator |"

        Design: Corner/roles/carrier_reviewer_cannot_create_plan
        """
        resp = api.create_plan(
            {"plan_name": "X", "sponsor_tax_id": "11-1111111"}, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_plan_accountant_cannot_adjudicate_claim(self, api):
        """PRD §2.1: "A well-authenticated request whose role is not
        permitted to invoke the endpoint is rejected with `ERR_FORBIDDEN`."
        PRD §4: "| POST | `/stop-loss/claims/{id}/adjudicate` | Adjudicate:
        SUBMITTED to ADJUDICATED | ClaimsExaminer |"

        Design: Corner/roles/plan_accountant_cannot_adjudicate_claim
        """
        plan = create_plan(plan_name="P", sponsor_tax_id="22-2222222")
        member = create_member(plan["id"], "M")
        claim = create_claim(plan["id"], member["id"],
                             billed_amount_cents=1_000_000)
        resp = api.adjudicate_claim(
            claim["id"], {"allowed_amount_cents": 1_000_000}, ACCOUNTANT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
