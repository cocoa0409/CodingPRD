"""The catalog loop is uncapped, and every traversal re-runs both content guards."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    UPC_1,
    UPC_2,
    ApiErrorId,
    CatalogDecision,
    CatalogState,
    fixtures,
    get_success_data,
    gtin14_for,
    make_retailer_buyer_headers,
    validate_error,
)
from test_helpers import factories as F

MINIMUM_SHELF_LIFE_DAYS = 30
REJECT_REASON = "Nutrition panel unreadable"


@pytest.fixture
def incomplete_item(api):
    """One item with no catalog data, plus a buyer identity to rule on it."""
    retailer = fixtures.create_retailer(api, total_store_count=1200)
    principal = fixtures.create_principal(api)
    return {
        "retailer": retailer,
        "principal": principal,
        "item": fixtures.create_item(api, principal["id"], upc=UPC_1),
    }


def submit_catalog(api, scope, **overrides):
    return api.submit_catalog(
        scope["item"]["id"],
        F.catalog_submission_payload(upc=UPC_1, **overrides),
        ACCOUNT_MANAGER_HEADERS,
    )


def decide_catalog(api, scope, **overrides):
    return api.decide_catalog(
        scope["item"]["id"],
        F.catalog_decision_payload(**overrides),
        make_retailer_buyer_headers(scope["retailer"]["id"]),
    )


def read_item(api, scope):
    return get_success_data(api.get_item(scope["item"]["id"], ACCOUNT_MANAGER_HEADERS), 200)


def submit_reject_resubmit(api, scope):
    get_success_data(submit_catalog(api, scope, shelf_life_days=MINIMUM_SHELF_LIFE_DAYS), 200)
    get_success_data(
        decide_catalog(api, scope, decision=CatalogDecision.REJECTED, reject_reason=REJECT_REASON),
        200,
    )
    return get_success_data(
        submit_catalog(
            api, scope, shelf_life_days=365, nutrition_panel_url="https://cdn.example/n1-fixed.pdf"
        ),
        200,
    )


class TestCatalogResubmissionCycle:
    def test_a_gtin_that_is_not_the_padded_upc_is_refused(self, api, incomplete_item):
        """The case code must be the item's own UPC behind two zeroes.

        PRD: "The `gtin14` must be exactly the two characters `00` followed by the item's own
        `upc`; anything else is `ERR_CATALOG_GTIN_MISMATCH`."

        Design: Corner/state_machines/catalog_rejection_cycle_resubmits_and_enforces_gtin_and_shelf_life
        """
        response = submit_catalog(api, incomplete_item, gtin14=gtin14_for(UPC_2))

        validate_error(response, ApiErrorId.CATALOG_GTIN_MISMATCH, 422)
        item = read_item(api, incomplete_item)
        assert item["catalog_state"] == CatalogState.INCOMPLETE
        assert item["catalog_submission_round"] == 0

    def test_shelf_life_below_the_trade_minimum_is_refused(self, api, incomplete_item):
        """Twenty days does not reach the thirty the trade requires.

        PRD: "And `shelf_life_days` must be at least the 30-day minimum the retail trade
        requires, otherwise `ERR_CATALOG_SHELF_LIFE_TOO_SHORT`."

        Design: Corner/state_machines/catalog_rejection_cycle_resubmits_and_enforces_gtin_and_shelf_life
        """
        response = submit_catalog(api, incomplete_item, shelf_life_days=20)

        validate_error(response, ApiErrorId.CATALOG_SHELF_LIFE_TOO_SHORT, 422)
        assert read_item(api, incomplete_item)["catalog_state"] == CatalogState.INCOMPLETE

    def test_exactly_the_minimum_shelf_life_passes_and_counts_a_round(
        self, api, incomplete_item
    ):
        """Thirty days is inside the bound, and the first traversal is recorded.

        PRD: "Catalog submission is the `BrokerAccountManager` action that carries all five: the
        case-level `gtin14`, the case dimensions `dimensions_cm` expressed as length by width by
        height in centimetres, the case `gross_weight_g` in grams of at least one gram, the
        `nutrition_panel_url` pointing at the panel asset, and `shelf_life_days`."

        Design: Corner/state_machines/catalog_rejection_cycle_resubmits_and_enforces_gtin_and_shelf_life
        """
        submitted = get_success_data(
            submit_catalog(api, incomplete_item, shelf_life_days=MINIMUM_SHELF_LIFE_DAYS), 200
        )

        assert submitted["catalog_state"] == CatalogState.SUBMITTED
        assert submitted["catalog_submission_round"] == 1
        assert submitted["shelf_life_days"] == MINIMUM_SHELF_LIFE_DAYS
        assert submitted["gtin14"] == gtin14_for(UPC_1)

    def test_a_rejection_without_a_reason_is_malformed(self, api, incomplete_item):
        """The buyer must say why, and the omission is caught in the shape band.

        PRD: "The `RetailerBuyer` then rules on the submitted data, supplying a `decision` of
        either `VALIDATED` or `REJECTED`; a rejection additionally requires `reject_reason`,
        whose absence is a malformed request."

        Design: Corner/state_machines/catalog_rejection_cycle_resubmits_and_enforces_gtin_and_shelf_life
        """
        get_success_data(
            submit_catalog(api, incomplete_item, shelf_life_days=MINIMUM_SHELF_LIFE_DAYS), 200
        )

        response = decide_catalog(api, incomplete_item, decision=CatalogDecision.REJECTED)

        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)
        assert read_item(api, incomplete_item)["catalog_state"] == CatalogState.SUBMITTED

    def test_the_rejection_records_the_reason_and_the_resubmission_clears_it(
        self, api, incomplete_item
    ):
        """Round two re-enters SUBMITTED with the reason wiped and the new data kept.

        PRD: "A rejected item is not a dead end: the account manager may correct the data and
        resubmit, moving `REJECTED` back to `SUBMITTED` under the same `gtin14` and shelf-life
        checks, incrementing `catalog_submission_round` again and clearing
        `catalog_reject_reason`."

        Design: Corner/state_machines/catalog_rejection_cycle_resubmits_and_enforces_gtin_and_shelf_life
        """
        get_success_data(
            submit_catalog(api, incomplete_item, shelf_life_days=MINIMUM_SHELF_LIFE_DAYS), 200
        )
        rejected = get_success_data(
            decide_catalog(
                api, incomplete_item, decision=CatalogDecision.REJECTED, reject_reason=REJECT_REASON
            ),
            200,
        )
        assert rejected["catalog_state"] == CatalogState.REJECTED
        assert rejected["catalog_reject_reason"] == REJECT_REASON

        resubmitted = get_success_data(
            submit_catalog(
                api,
                incomplete_item,
                shelf_life_days=365,
                nutrition_panel_url="https://cdn.example/n1-fixed.pdf",
            ),
            200,
        )

        assert resubmitted["catalog_state"] == CatalogState.SUBMITTED
        assert resubmitted["catalog_submission_round"] == 2
        assert resubmitted["catalog_reject_reason"] is None
        assert resubmitted["shelf_life_days"] == 365

    def test_the_guards_run_again_on_every_traversal(self, api, incomplete_item):
        """A wrong gtin and a short shelf life are refused just as hard from REJECTED.

        PRD: "Two content rules are checked."

        Design: Corner/state_machines/catalog_rejection_cycle_resubmits_and_enforces_gtin_and_shelf_life
        """
        get_success_data(
            submit_catalog(api, incomplete_item, shelf_life_days=MINIMUM_SHELF_LIFE_DAYS), 200
        )
        get_success_data(
            decide_catalog(
                api, incomplete_item, decision=CatalogDecision.REJECTED, reject_reason=REJECT_REASON
            ),
            200,
        )

        validate_error(
            submit_catalog(api, incomplete_item, gtin14=gtin14_for(UPC_2)),
            ApiErrorId.CATALOG_GTIN_MISMATCH,
            422,
        )
        validate_error(
            submit_catalog(api, incomplete_item, shelf_life_days=29),
            ApiErrorId.CATALOG_SHELF_LIFE_TOO_SHORT,
            422,
        )
        assert read_item(api, incomplete_item)["catalog_state"] == CatalogState.REJECTED

    def test_validation_is_terminal_and_closes_the_loop(self, api, incomplete_item):
        """Once validated, a further catalog submission has no transition to take.

        PRD: "Validation moves `catalog_state` from `SUBMITTED` to `VALIDATED`, which is
        terminal: the item is now eligible to appear in a submitted presentation and to be
        awarded an authorization, and the `prep_completeness_bps` of every `DRAFT` presentation
        listing this item is recomputed."

        Design: Corner/state_machines/catalog_rejection_cycle_resubmits_and_enforces_gtin_and_shelf_life
        """
        submit_reject_resubmit(api, incomplete_item)

        validated = get_success_data(
            decide_catalog(api, incomplete_item, decision=CatalogDecision.VALIDATED), 200
        )
        assert validated["catalog_state"] == CatalogState.VALIDATED

        validate_error(
            submit_catalog(api, incomplete_item, shelf_life_days=365),
            ApiErrorId.INVALID_STATE,
            409,
        )
