"""The five roles are peers: each one's exclusive writes are a 403 for the other four."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    AUDIT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    CLOCK_DEFAULT_UTC,
    NON_EXISTENT_UUID,
    PRIMARY_CATEGORY,
    ApiErrorId,
    DeductionReasonCode,
    DisputeState,
    UPC_1,
    UPC_2,
    fixtures,
    get_success_data,
    make_principal_portal_headers,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F

AMOUNT_CENTS = 60000
BUDGET_CENTS = 20000000
LATER_INSTANT = "2026-08-02T00:00:00Z"


@pytest.fixture
def one_chain_one_principal_one_item_one_deduction(api):
    """The smallest world in which every role has something it is not allowed to touch."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api, slotting_budget_cents=BUDGET_CENTS)
    item = fixtures.create_item(api, principal["id"], upc=UPC_1)
    deduction = fixtures.create_deduction(
        api,
        retailer["id"],
        principal["id"],
        reason_code=DeductionReasonCode.SHORTAGE,
        amount_cents=AMOUNT_CENTS,
        deduction_date="2026-08-01",
    )
    return {
        "retailer": retailer,
        "principal": principal,
        "item": item,
        "deduction": deduction,
        "buyer_headers": make_retailer_buyer_headers(retailer["id"]),
        "portal_headers": make_principal_portal_headers(principal["id"]),
    }


def attempt_chain_registration(api, headers):
    return api.create_retailer(
        F.retailer_payload(name="Ghost Chain", chain_code="GHOST", total_store_count=10), headers
    )


def attempt_item_setup(api, scope, headers):
    return api.create_item(
        F.item_payload(
            scope["principal"]["id"], upc=UPC_2, description="Frozen Empanadas 10ct"
        ),
        headers,
    )


def total_count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


class TestExclusiveOperationsAreClosedToPeerRoles:
    def test_the_contract_surface_is_closed_to_the_account_manager_and_the_portal_user(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """Registering chains, drafting rate cards and moving budgets belong to one role only.

        PRD: "`BrokerAdmin` — the broker's contract administrator. Registers retail chains, onboards
        principals, adjusts principal budgets and status, drafts and activates commission agreements, and
        declares or waives principal conflict rules."

        PRD: "When the headers are well formed but the role is not authorized for the requested
        operation, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction

        validate_error(
            attempt_chain_registration(api, ACCOUNT_MANAGER_HEADERS),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            attempt_chain_registration(api, scope["portal_headers"]),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.create_agreement(
                F.agreement_payload(scope["principal"]["id"], scope["retailer"]["id"]),
                ACCOUNT_MANAGER_HEADERS,
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.patch_principal(
                scope["principal"]["id"],
                F.principal_patch_payload(slotting_budget_cents=1),
                scope["portal_headers"],
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

    def test_none_of_the_refused_contract_writes_left_a_trace(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """A priority-2 rejection happens before any persistence work.

        PRD: "**Role permission.** The acting role appears in the endpoint's authorized list — otherwise
        `ERR_ROLE_FORBIDDEN` (403)."

        PRD: "Validations are evaluated in ascending priority bands, and the **first** violated rule
        determines the response."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction
        # Recording the chain's deduction already re-derived this principal's aggregates,
        # so the pre-refusal version is read here rather than assumed to be 1.
        version_before = fixtures.get_principal(api, scope["principal"]["id"])["version"]
        validate_error(
            attempt_chain_registration(api, ACCOUNT_MANAGER_HEADERS),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.create_agreement(
                F.agreement_payload(scope["principal"]["id"], scope["retailer"]["id"]),
                ACCOUNT_MANAGER_HEADERS,
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.patch_principal(
                scope["principal"]["id"],
                F.principal_patch_payload(slotting_budget_cents=1),
                scope["portal_headers"],
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

        assert total_count(api.list_retailers(BROKER_ADMIN_HEADERS)) == 1
        assert total_count(api.list_agreements(BROKER_ADMIN_HEADERS)) == 0
        principal = fixtures.get_principal(api, scope["principal"]["id"])
        assert principal["slotting_budget_cents"] == BUDGET_CENTS
        assert principal["version"] == version_before

    def test_item_setup_is_closed_to_the_buyer_and_the_audit_manager(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """The chain that will stock the item may not create it, and neither may audit.

        PRD: "| POST | `/items` | New item setup for a principal | BrokerAccountManager |"

        PRD: "`BrokerAccountManager` — the broker's account team. Sets up new items and submits catalog
        data, prepares and submits presentations, carries the broker side of a slotting negotiation, plans
        and executes promotions and demos, and files, substantiates or concedes post-audit claims."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction

        validate_error(
            attempt_item_setup(api, scope, scope["buyer_headers"]),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            attempt_item_setup(api, scope, AUDIT_MANAGER_HEADERS),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

        assert total_count(api.list_items(ACCOUNT_MANAGER_HEADERS)) == 1

    def test_the_calendar_and_the_catalog_decision_belong_to_the_buyer_alone(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """Not even the contract administrator may rule on catalog data or schedule a review.

        PRD: "| POST | `/items/{itemId}/catalog-decision` | Validate or reject submitted catalog data |
        RetailerBuyer |"

        PRD: "| POST | `/category-reviews` | Schedule a category review with its decision window,
        submission deadline and slot count | RetailerBuyer |"

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction

        validate_error(
            api.decide_catalog(
                scope["item"]["id"],
                F.catalog_decision_payload("VALIDATED"),
                BROKER_ADMIN_HEADERS,
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.create_review(
                F.review_payload(scope["retailer"]["id"]), ACCOUNT_MANAGER_HEADERS
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

        assert total_count(api.list_reviews(BROKER_ADMIN_HEADERS)) == 0

    def test_the_role_check_outranks_both_the_shape_and_the_existence_bands(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """The snapshot body names an unknown authorization and a non-integer version pin.

        PRD: "| POST | `/distribution-snapshots` | Post one period of store-level distribution |
        RetailerBuyer |"

        PRD: "Later violations are never reported, so a request that breaks three rules always returns
        the code of the earliest band it fails."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        response = api.post_snapshot(
            F.snapshot_payload(
                NON_EXISTENT_UUID,
                "not-a-version",
                period_index=1,
                reported_store_count=10,
                distributed_store_count=10,
                reported_case_volume=10,
            ),
            BROKER_ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.ROLE_FORBIDDEN, 403)
        assert total_count(api.list_snapshots(BROKER_ADMIN_HEADERS)) == 0

    def test_recording_a_deduction_is_the_chains_own_act(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """The broker cannot short-pay itself, so the account manager may not file the charge.

        PRD: "| POST | `/deductions` | Record a deduction the chain has taken against a principal |
        RetailerBuyer |"

        PRD: "`RetailerBuyer` — the retail category buyer. Owns the category review calendar, catalog
        validation decisions, the retailer side of a slotting negotiation, the award decision, store-level
        distribution reporting, authorization voids and the deductions the chain takes."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction

        response = api.create_deduction(
            F.deduction_payload(
                scope["retailer"]["id"],
                scope["principal"]["id"],
                reason_code=DeductionReasonCode.SHORTAGE,
                amount_cents=999,
                deduction_date="2026-08-01",
            ),
            ACCOUNT_MANAGER_HEADERS,
        )

        validate_error(response, ApiErrorId.ROLE_FORBIDDEN, 403)
        assert total_count(api.list_deductions(AUDIT_MANAGER_HEADERS)) == 1

    def test_the_two_deduction_verbs_are_split_between_two_broker_roles(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """Filing is the account team's; ruling on the claim is audit's; neither may borrow the other.

        PRD: "| POST | `/deductions/{deductionId}/dispute` | File or refile a post-audit claim inside the
        chain's dispute window | BrokerAccountManager |"

        PRD: "`BrokerAuditManager` — the broker's deduction-audit control. The sole approver or denier of
        a post-audit recovery."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction
        deduction_id = scope["deduction"]["id"]

        validate_error(
            api.dispute_deduction(
                deduction_id, F.dispute_payload(AMOUNT_CENTS), AUDIT_MANAGER_HEADERS
            ),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )
        validate_error(
            api.approve_recovery(deduction_id, ACCOUNT_MANAGER_HEADERS),
            ApiErrorId.ROLE_FORBIDDEN,
            403,
        )

        filed = get_success_data(
            api.dispute_deduction(
                deduction_id, F.dispute_payload(AMOUNT_CENTS), ACCOUNT_MANAGER_HEADERS
            ),
            200,
        )
        assert filed["dispute_state"] == DisputeState.FILED

    def test_the_commission_statement_is_the_one_read_the_buyer_is_denied(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """Every other GET is shared by all five roles; this computed read is not.

        PRD: "| GET | `/principals/{principalId}/commission-statement` | Computed read: per-item
        commission lines and totals for one chain and category | BrokerAdmin, BrokerAccountManager,
        BrokerAuditManager, PrincipalPortalUser |"

        PRD: "The commission statement is a computed read, available to `BrokerAdmin`,
        `BrokerAccountManager`, `BrokerAuditManager` and `PrincipalPortalUser` — but not to a
        `RetailerBuyer`."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction

        response = api.get_commission_statement(
            scope["principal"]["id"],
            scope["buyer_headers"],
            {"retailer_id": scope["retailer"]["id"], "category_code": PRIMARY_CATEGORY},
        )

        validate_error(response, ApiErrorId.ROLE_FORBIDDEN, 403)

    def test_the_clock_write_and_every_chain_read_are_shared_by_all_five_roles(
        self, api, one_chain_one_principal_one_item_one_deduction
    ):
        """The read-only portal user may still move the logical clock.

        PRD: "| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | BrokerAdmin,
        BrokerAccountManager, BrokerAuditManager, RetailerBuyer, PrincipalPortalUser |"

        PRD: "This role holds no write capability anywhere on the business surface — every mutating
        operation other than setting the logical clock returns `ERR_ROLE_FORBIDDEN`."

        Design: Corner/rbac/every_exclusive_operation_is_rejected_for_the_other_four_roles
        """
        scope = one_chain_one_principal_one_item_one_deduction

        advanced = get_success_data(
            api.set_clock(F.clock_payload(LATER_INSTANT), scope["portal_headers"]), 200
        )
        chain_read_by_audit = get_success_data(
            api.get_retailer(scope["retailer"]["id"], AUDIT_MANAGER_HEADERS), 200
        )

        assert advanced["current_utc"] == LATER_INSTANT
        assert advanced["current_utc"] != CLOCK_DEFAULT_UTC
        assert chain_read_by_audit["name"] == scope["retailer"]["name"]
