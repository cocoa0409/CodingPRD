"""Access control: user-context headers, role authorization, and
segregation-of-duties rules (including its priority over fiscal checks)."""
from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_carrier_payload,
    create_reserve_payload,
    setup_claim_appealed,
    setup_claim_offered,
    setup_claim_under_review,
    validate_error,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
SALVAGE = TEST_USERS["salvage_headers"]
ADJUSTER_USER_ID = "user-adjuster-1"


class TestUserContextHeaders:
    def test_missing_user_context_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.list_carriers(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_clerk_cannot_register_carrier(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST | `/freight-claims/carriers` | Register a carrier | ClaimsManager"

        Design: Corner/validations/wrong_role_denied
        """
        payload = create_carrier_payload()
        resp = api.create_carrier(payload, CLERK)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestRoleExclusiveOperations:
    def test_clerk_cannot_decide_appeal(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST | `/freight-claims/claims/{id}/appeals/{appealId}/decide` | Decide an appeal | ClaimsManager"

        Design: Corner/roles/rbac_clerk_cannot_decide_appeal
        """
        ctx = setup_claim_appealed()
        resp = api.decide_appeal(
            ctx["claim"]["id"],
            ctx["appeal"]["id"],
            {"decision": "OVERTURN", "decided_amount_cents": 40_000},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_salvage_coordinator_cannot_post_reserve(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: "POST | `/freight-claims/claims/{id}/reserves` | Post a reserve on a claim (only one open at a time) | FinanceController"

        Design: Corner/roles/rbac_salvage_coordinator_cannot_post_reserve
        """
        ctx = setup_claim_under_review()
        resp = api.post_reserve(
            ctx["claim"]["id"], create_reserve_payload(5_000), SALVAGE
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestSegregationOfDuties:
    def test_settlement_accept_by_assessment_author_rejected(self, api):
        """PRD §3.6: "A `ClaimsManager` or `FinanceController` accepts an offer only when the claim is `OFFERED` (otherwise `ERR_CLAIM_INVALID_STATE`), the settlement is `OFFERED` (otherwise `ERR_SETTLEMENT_INVALID_STATE`), the amount does not exceed the claim's current `net_exposure_cents` (otherwise `ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE`), the actor's authority is at least the offer's `authority_tier_required` — tiers are cumulative, so `TIER_3` satisfies `TIER_2` and `TIER_1` requirements — with a shortfall producing `ERR_AUTHORITY_TIER_INSUFFICIENT`, the actor is neither the user who extended the offer nor the adjuster who performed the assessment (a same-user overlap is `ERR_SEGREGATION_OF_DUTIES_VIOLATION`), and the claim's `reserve_amount_cents` covers the full amount (otherwise `ERR_RESERVE_INSUFFICIENT`)."

        Design: Corner/roles/rbac_segregation_of_duties_settlement
        """
        # Assessment authored by ADJUSTER (user-adjuster-1); offer extended by
        # ADJUSTER2; reserve fully covers the amount; accept attempted by a
        # ClaimsManager carrying the SAME X-User-ID as the assessment author.
        ctx = setup_claim_offered(amount_cents=40_000, reserve_amount_cents=40_000)
        accept_headers = build_user_headers(ADJUSTER_USER_ID, "ClaimsManager")
        resp = api.accept_settlement(
            ctx["claim"]["id"], ctx["settlement"]["id"], accept_headers
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_segregation_violation_reported_before_reserve_shortfall(self, api):
        """PRD §2.9: "When several validations could apply to the same request, they are evaluated in a fixed priority order, and the earliest failure is the one reported."
        PRD §2.9: "Because claim state is checked before optimistic concurrency, a claim in the wrong state reports `ERR_CLAIM_INVALID_STATE` even when the request also carries a stale version; because segregation of duties outranks fiscal checks, a forbidden same-user approval surfaces as `ERR_SEGREGATION_OF_DUTIES_VIOLATION` rather than being masked by a later amount check."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_settlement_accept
        """
        # Reserve (10_000) deliberately insufficient for the 40_000 offer AND
        # the acceptor is the assessment author: both (6) and (11) hold.
        ctx = setup_claim_offered(amount_cents=40_000, reserve_amount_cents=10_000)
        accept_headers = build_user_headers(ADJUSTER_USER_ID, "ClaimsManager")
        resp = api.accept_settlement(
            ctx["claim"]["id"], ctx["settlement"]["id"], accept_headers
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

    def test_accept_with_insufficient_reserve_rejected(self, api):
        """PRD §3.6: "A `ClaimsManager` or `FinanceController` accepts an offer only when the claim is `OFFERED` (otherwise `ERR_CLAIM_INVALID_STATE`), the settlement is `OFFERED` (otherwise `ERR_SETTLEMENT_INVALID_STATE`), the amount does not exceed the claim's current `net_exposure_cents` (otherwise `ERR_SETTLEMENT_EXCEEDS_NET_EXPOSURE`), the actor's authority is at least the offer's `authority_tier_required` — tiers are cumulative, so `TIER_3` satisfies `TIER_2` and `TIER_1` requirements — with a shortfall producing `ERR_AUTHORITY_TIER_INSUFFICIENT`, the actor is neither the user who extended the offer nor the adjuster who performed the assessment (a same-user overlap is `ERR_SEGREGATION_OF_DUTIES_VIOLATION`), and the claim's `reserve_amount_cents` covers the full amount (otherwise `ERR_RESERVE_INSUFFICIENT`)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_settlement_accept
        """
        # Isolated reserve shortfall: acceptor is a fresh manager identity, so
        # only the reserve-coverage check can fail.
        ctx = setup_claim_offered(amount_cents=40_000, reserve_amount_cents=10_000)
        resp = api.accept_settlement(
            ctx["claim"]["id"], ctx["settlement"]["id"], MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_RESERVE_INSUFFICIENT)
