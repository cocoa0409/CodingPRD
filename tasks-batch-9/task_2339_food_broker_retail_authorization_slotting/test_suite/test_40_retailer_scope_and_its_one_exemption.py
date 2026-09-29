"""A buyer is locked to its own chain everywhere except on the chain-agnostic catalog decision."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    ApiErrorId,
    CatalogState,
    DeductionReasonCode,
    ReviewStatus,
    fixtures,
    get_success_data,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F


@pytest.fixture
def two_chains_and_one_submitted_item(api):
    """BIGMART owns a SCHEDULED review; MIDCO owns nothing that follows."""
    owner = fixtures.create_retailer(api, name="Bigmart", chain_code="BIGMART")
    outsider = fixtures.create_retailer(
        api, name="Midco", chain_code="MIDCO", total_store_count=400
    )
    bundle = fixtures.active_principal(api, owner["id"])
    principal = bundle["principal"]
    item = fixtures.create_item(api, principal["id"])
    item = get_success_data(
        api.submit_catalog(item["id"], F.catalog_submission_payload(), ACCOUNT_MANAGER_HEADERS),
        200,
    )
    review = fixtures.create_review(api, owner["id"])
    return {
        "owner": owner,
        "outsider": outsider,
        "principal": principal,
        "item": item,
        "review": review,
    }


def outsider_headers(scope):
    return make_retailer_buyer_headers(scope["outsider"]["id"])


def owner_headers(scope):
    return make_retailer_buyer_headers(scope["owner"]["id"])


class TestRetailerScopeAndItsOneExemption:
    def test_an_outside_buyer_cannot_open_another_chains_review(
        self, api, two_chains_and_one_submitted_item
    ):
        """The review's retailer_id does not resolve to the acting buyer's identifier.

        PRD: "When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting
        `Retailer`; every write must target a resource whose retail chain resolves to that same
        identifier — a review's `retailer_id`, a slotting deal through its presentation's review to
        that review's `retailer_id`, an authorization's `retailer_id`, a distribution ledger entry
        through its authorization's `retailer_id`, and a deduction's `retailer_id`."

        Design: Corner/validations/retailer_scope_is_enforced_except_on_chain_agnostic_catalog_decisions
        """
        scope = two_chains_and_one_submitted_item

        response = api.open_review(scope["review"]["id"], outsider_headers(scope))

        validate_error(response, ApiErrorId.RETAILER_SCOPE_FORBIDDEN, 403)
        assert (
            fixtures.get_review(api, scope["review"]["id"], scope["owner"]["id"])["status"]
            == ReviewStatus.SCHEDULED
        )

    def test_an_outside_buyer_cannot_schedule_a_review_for_another_chain(
        self, api, two_chains_and_one_submitted_item
    ):
        """The payload names BIGMART while the acting identity is MIDCO.

        PRD: "A `RetailerBuyer` acting outside its own chain returns
        `ERR_RETAILER_SCOPE_FORBIDDEN` (403); a `PrincipalPortalUser` reading another principal's
        resource returns `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (403)."

        Design: Corner/validations/retailer_scope_is_enforced_except_on_chain_agnostic_catalog_decisions
        """
        scope = two_chains_and_one_submitted_item

        response = api.create_review(
            F.review_payload(
                scope["owner"]["id"],
                review_window_start="2026-10-01",
                review_window_end="2026-10-15",
                submission_deadline="2026-09-20T00:00:00Z",
            ),
            outsider_headers(scope),
        )

        validate_error(response, ApiErrorId.RETAILER_SCOPE_FORBIDDEN, 403)
        rows, meta = validate_paginated(
            api.list_reviews(BROKER_ADMIN_HEADERS, {"retailer_id": scope["owner"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == scope["review"]["id"]

    def test_an_outside_buyer_cannot_record_a_deduction_against_another_chain(
        self, api, two_chains_and_one_submitted_item
    ):
        """A deduction carries its own retailer_id, and that is what the scope check reads.

        PRD: "When `X-User-Role` is `RetailerBuyer`, `X-User-ID` is the `id` of the acting
        `Retailer`; every write must target a resource whose retail chain resolves to that same
        identifier — a review's `retailer_id`, a slotting deal through its presentation's review to
        that review's `retailer_id`, an authorization's `retailer_id`, a distribution ledger entry
        through its authorization's `retailer_id`, and a deduction's `retailer_id`."

        Design: Corner/validations/retailer_scope_is_enforced_except_on_chain_agnostic_catalog_decisions
        """
        scope = two_chains_and_one_submitted_item

        response = api.create_deduction(
            F.deduction_payload(
                scope["owner"]["id"],
                scope["principal"]["id"],
                reason_code=DeductionReasonCode.SHORTAGE,
                amount_cents=50000,
            ),
            outsider_headers(scope),
        )

        validate_error(response, ApiErrorId.RETAILER_SCOPE_FORBIDDEN, 403)
        _, meta = validate_paginated(api.list_deductions(BROKER_ADMIN_HEADERS))
        assert meta["total_count"] == 0

    def test_any_buyer_may_rule_on_catalog_data(self, api, two_chains_and_one_submitted_item):
        """MIDCO owns no part of this item and still validates it.

        PRD: "This is the one buyer action exempt from chain ownership scope, because items are
        chain-agnostic."

        Design: Corner/validations/retailer_scope_is_enforced_except_on_chain_agnostic_catalog_decisions
        """
        scope = two_chains_and_one_submitted_item

        decided = get_success_data(
            api.decide_catalog(
                scope["item"]["id"],
                F.catalog_decision_payload(),
                outsider_headers(scope),
            ),
            200,
        )

        assert decided["catalog_state"] == CatalogState.VALIDATED

    def test_the_owning_buyer_makes_the_same_call_successfully(
        self, api, two_chains_and_one_submitted_item
    ):
        """The scope rule refuses the caller, never the request itself.

        PRD: "Opening a review moves `status` from `SCHEDULED` to `OPEN` and requires the logical
        clock to be strictly before `submission_deadline`, otherwise `ERR_REVIEW_SUBMISSION_CLOSED`;
        once open, presentations may be submitted."

        Design: Corner/validations/retailer_scope_is_enforced_except_on_chain_agnostic_catalog_decisions
        """
        scope = two_chains_and_one_submitted_item
        validate_error(
            api.open_review(scope["review"]["id"], outsider_headers(scope)),
            ApiErrorId.RETAILER_SCOPE_FORBIDDEN,
            403,
        )

        opened = get_success_data(
            api.open_review(scope["review"]["id"], owner_headers(scope)), 200
        )

        assert opened["status"] == ReviewStatus.OPEN
