"""Reads echo what was stored, and a partial principal patch re-derives the posture in place."""

import pytest

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    DEFAULT_DEDUCTION_DISPUTE_WINDOW_DAYS,
    CreditPosture,
    DeductionReasonCode,
    fixtures,
    get_success_data,
    make_principal_portal_headers,
    validate_paginated,
)
from test_helpers import factories as F

CHAIN_CODE = "BIGMART"
CUSTOM_AT_RISK_BPS = 900
CUSTOM_MAX_DEMOS = 1
ORIGINAL_BUDGET_CENTS = 1000000
HALVED_BUDGET_CENTS = 500000
DEDUCTION_CENTS = 500000
NEW_NAME = "Northwind Foods Inc"


@pytest.fixture
def chain_and_principal_on_watch(api):
    """A chain with two non-default policy fields, and a principal at exactly 5,000 bps."""
    retailer = fixtures.create_retailer(
        api,
        total_store_count=1200,
        at_risk_void_rate_bps=CUSTOM_AT_RISK_BPS,
        max_concurrent_demos=CUSTOM_MAX_DEMOS,
    )
    principal = fixtures.create_principal(api, slotting_budget_cents=ORIGINAL_BUDGET_CENTS)
    deduction = fixtures.create_deduction(
        api,
        retailer["id"],
        principal["id"],
        reason_code=DeductionReasonCode.SHORTAGE,
        amount_cents=DEDUCTION_CENTS,
        deduction_date="2026-08-01",
    )
    return {"retailer": retailer, "principal": principal, "deduction": deduction}


def patch_principal(api, scope, **fields):
    return get_success_data(
        api.patch_principal(
            scope["principal"]["id"],
            F.principal_patch_payload(**fields),
            BROKER_ADMIN_HEADERS,
        ),
        200,
    )


class TestRetailerAndPrincipalCrudRoundTrip:
    def test_reading_a_chain_returns_the_stored_policy_without_touching_the_version(
        self, api, chain_and_principal_on_watch
    ):
        """Two policy fields were supplied, one was omitted and took its declared default.

        PRD: "The chain record is also where the retailer's operating policy lives, and each policy
        field has a declared default that applies when the field is omitted at registration."

        PRD: "Mutable resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on
        every change to the resource, and `version`, an integer that is 1 when the resource is created
        and increases by exactly one on every mutation of that resource."

        Design: Corner/endpoints/retailer_and_principal_crud_round_trip_with_patch_semantics
        """
        scope = chain_and_principal_on_watch

        stored = get_success_data(
            api.get_retailer(scope["retailer"]["id"], ACCOUNT_MANAGER_HEADERS), 200
        )

        assert stored["name"] == "Bigmart"
        assert stored["chain_code"] == CHAIN_CODE
        assert stored["total_store_count"] == 1200
        assert stored["at_risk_void_rate_bps"] == CUSTOM_AT_RISK_BPS
        assert stored["max_concurrent_demos"] == CUSTOM_MAX_DEMOS
        assert stored["deduction_dispute_window_days"] == DEFAULT_DEDUCTION_DISPUTE_WINDOW_DAYS
        assert stored["version"] == scope["retailer"]["version"] == 1

    def test_the_chain_code_filter_returns_exactly_the_registered_chain(
        self, api, chain_and_principal_on_watch
    ):
        """The one filter the chain collection offers.

        PRD: "Retail chains may be filtered by `chain_code`."

        Design: Corner/endpoints/retailer_and_principal_crud_round_trip_with_patch_semantics
        """
        scope = chain_and_principal_on_watch

        rows, meta = validate_paginated(
            api.list_retailers(ACCOUNT_MANAGER_HEADERS, {"chain_code": CHAIN_CODE})
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [scope["retailer"]["id"]]

    def test_the_portal_user_reads_its_own_principal_with_the_derived_aggregates(
        self, api, chain_and_principal_on_watch
    ):
        """500,000 open against a 1,000,000 budget is exactly the inclusive WATCH threshold.

        PRD: "failing that it is `WATCH` when `at_risk_authorization_count` is 1 or more, or
        `liability_ratio_bps` is 5,000 or more, being fifty percent of the budget"

        PRD: "When `X-User-Role` is `PrincipalPortalUser`, `X-User-ID` is the `id` of the acting
        `Principal`; reading an item, a presentation, a deduction, or a slotting deal (through its
        presentation) that belongs to a different principal is rejected with
        `ERR_PRINCIPAL_SCOPE_FORBIDDEN` (HTTP 403)."

        Design: Corner/endpoints/retailer_and_principal_crud_round_trip_with_patch_semantics
        """
        scope = chain_and_principal_on_watch
        principal_id = scope["principal"]["id"]

        own_view = get_success_data(
            api.get_principal(principal_id, make_principal_portal_headers(principal_id)), 200
        )

        assert own_view["open_deduction_cents"] == DEDUCTION_CENTS
        assert own_view["liability_ratio_bps"] == 5000
        assert own_view["credit_posture"] == CreditPosture.WATCH

    def test_patching_only_the_name_leaves_the_budget_and_the_posture_alone(
        self, api, chain_and_principal_on_watch
    ):
        """The omitted `slotting_budget_cents` keeps its stored value rather than being nulled.

        PRD: "A `BrokerAdmin` may later adjust the principal's `name` or `slotting_budget_cents`;
        because the budget is the denominator of the liability ratio, changing it immediately re-derives
        `liability_ratio_bps` and `credit_posture` and advances the principal's `version`."

        Design: Corner/endpoints/retailer_and_principal_crud_round_trip_with_patch_semantics
        """
        scope = chain_and_principal_on_watch
        before = fixtures.get_principal(api, scope["principal"]["id"])

        renamed = patch_principal(api, scope, name=NEW_NAME)

        assert renamed["name"] == NEW_NAME
        assert renamed["code"] == scope["principal"]["code"]
        assert renamed["slotting_budget_cents"] == ORIGINAL_BUDGET_CENTS
        assert renamed["credit_posture"] == CreditPosture.WATCH
        assert renamed["version"] == before["version"] + 1

    def test_halving_the_budget_re_derives_the_posture_in_the_patch_response(
        self, api, chain_and_principal_on_watch
    ):
        """The same 500,000 charge is now the whole budget, which is 10,000 basis points.

        PRD: "A `BrokerAdmin` may later adjust the principal's `name` or `slotting_budget_cents`;
        because the budget is the denominator of the liability ratio, changing it immediately re-derives
        `liability_ratio_bps` and `credit_posture` and advances the principal's `version`."

        PRD: "it is `RESTRICTED` when `at_risk_authorization_count` is 2 or more, or
        `liability_ratio_bps` is 7,500 or more — that is, when open liability plus open deductions reach
        seventy-five percent of the budget"

        Design: Corner/endpoints/retailer_and_principal_crud_round_trip_with_patch_semantics
        """
        scope = chain_and_principal_on_watch
        renamed = patch_principal(api, scope, name=NEW_NAME)

        rebudgeted = patch_principal(api, scope, slotting_budget_cents=HALVED_BUDGET_CENTS)

        assert rebudgeted["name"] == NEW_NAME
        assert rebudgeted["slotting_budget_cents"] == HALVED_BUDGET_CENTS
        assert rebudgeted["liability_ratio_bps"] == 10000
        assert rebudgeted["credit_posture"] == CreditPosture.RESTRICTED
        assert rebudgeted["version"] == renamed["version"] + 1

    def test_both_patches_are_persisted_and_a_read_adds_no_further_version(
        self, api, chain_and_principal_on_watch
    ):
        """The second read returns exactly what the second patch returned.

        PRD: "A change to a *derived* field counts as a mutation: when an accepted slotting fee moves a
        principal's committed total, or a distribution posting moves an authorization's void counters,
        the affected resource's `updated_at` is refreshed and its `version` advances."

        Design: Corner/endpoints/retailer_and_principal_crud_round_trip_with_patch_semantics
        """
        scope = chain_and_principal_on_watch
        patch_principal(api, scope, name=NEW_NAME)
        rebudgeted = patch_principal(api, scope, slotting_budget_cents=HALVED_BUDGET_CENTS)

        reread = fixtures.get_principal(api, scope["principal"]["id"])

        assert reread["name"] == NEW_NAME
        assert reread["slotting_budget_cents"] == HALVED_BUDGET_CENTS
        assert reread["credit_posture"] == CreditPosture.RESTRICTED
        assert reread["version"] == rebudgeted["version"]
        assert reread["updated_at"] == rebudgeted["updated_at"]
