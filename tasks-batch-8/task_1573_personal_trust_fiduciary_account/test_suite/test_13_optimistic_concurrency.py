"""Optimistic concurrency on TrustAccount.version for the two OCC-guarded
writes (PRD §2.7)."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    MANAGER,
    OFFICER,
    buy_holding,
    create_request,
    get_trust,
    post_receipt,
    setup_funded_trust,
    create_active_trust,
    trust_version,
)


class TestOccOnRequestCreate:
    def _occ_ctx(self, api):
        ctx = setup_funded_trust(
            income_cents=5000000,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            trust_name="OCC Req",
        )
        return ctx["trust"], ctx["beneficiaries"][0]

    def test_first_create_succeeds_with_current_version(self, api):
        """PRD §2.7: "Creating a distribution request (`POST
        /trusts/distribution-requests`) requires the request body to carry
        `expected_trust_account_version`, holding the trust `version` the
        client last observed; if another writer has advanced the trust's
        version since that observation — for example, a prior request creation
        or any balance-affecting cascade that moved
        `pending_distribution_count` or the available balances — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's
        view of available funds is stale."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_request_create
        """
        trust, ben = self._occ_ctx(api)
        req = create_request(trust["id"], ben["id"], amount_cents=100000)
        assert req["status"] == "SUBMITTED"

    def test_second_create_with_stale_version_rejected(self, api):
        """PRD §2.7: "Creating a distribution request (`POST
        /trusts/distribution-requests`) requires the request body to carry
        `expected_trust_account_version`, holding the trust `version` the
        client last observed; if another writer has advanced the trust's
        version since that observation — for example, a prior request creation
        or any balance-affecting cascade that moved
        `pending_distribution_count` or the available balances — the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's
        view of available funds is stale."
        PRD §3.3: "A successful create lands in SUBMITTED, increments the
        trust's `pending_distribution_count` by one, and increments the
        trust's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_request_create
        """
        trust, ben = self._occ_ctx(api)
        observed = trust_version(trust["id"])
        first = create_request(trust["id"], ben["id"], amount_cents=100000)
        assert first["status"] == "SUBMITTED"

        resp = api.create_distribution_request(
            {
                "trust_id": trust["id"],
                "beneficiary_id": ben["id"],
                "amount_cents": 200000,
                "allocation_source": "INCOME_ONLY",
                "purpose_category": "OTHER",
                "expected_trust_account_version": observed,
            },
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_trust(trust["id"])
        assert after["pending_distribution_count"] == 1, (
            "the rejected create must leave no residue"
        )


class TestOccOnHoldingCreate:
    def _funded(self, api):
        trust = create_active_trust(trust_name="OCC Hold")
        post_receipt(trust["id"], 100000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        return trust

    def test_first_purchase_succeeds_with_current_version(self, api):
        """PRD §2.7: "Purchasing an investment holding (`POST
        /trusts/investment-holdings`) works identically: the body must carry
        `expected_trust_account_version` matching the trust's current
        `version`, and a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412), since a prior purchase legitimately debited principal cash
        and advanced the version."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_holding_create
        """
        trust = self._funded(api)
        holding = buy_holding(trust["id"], "EQUITY", "AAA", 10, 100000)
        assert holding["market_value_cents"] == 1000000

    def test_second_purchase_with_stale_version_rejected(self, api):
        """PRD §2.7: "Purchasing an investment holding (`POST
        /trusts/investment-holdings`) works identically: the body must carry
        `expected_trust_account_version` matching the trust's current
        `version`, and a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412), since a prior purchase legitimately debited principal cash
        and advanced the version. No other endpoint takes a version field."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_holding_create
        """
        trust = self._funded(api)
        observed = trust_version(trust["id"], MANAGER)
        buy_holding(trust["id"], "EQUITY", "AAA", 10, 100000)

        resp = api.create_holding(
            {
                "trust_id": trust["id"],
                "asset_class": "EQUITY",
                "ticker": "BBB",
                "units": 10,
                "unit_price_cents": 100000,
                "expected_trust_account_version": observed,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        rows, _ = validate_paginated(
            api.list_holdings(MANAGER, params={"trust_id": trust["id"]})
        )
        assert all(h["ticker"] != "BBB" for h in rows), "no BBB holding may exist"
