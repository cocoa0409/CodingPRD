"""Gates that fire on a configuration, an aggregate or a third entity.

Each rule here is proved by contrast: the same request is refused under one
offering rule and accepted under another, refused for the collective total while
each order is individually fine, or refused for one funding source and accepted
for the other.
"""

from test_helpers import (
    CANONICAL_OPERATING_TRUST,
    EXCHANGE_FILE_B,
    EXCHANGE_FILE_C,
    INVESTOR_A,
    INVESTOR_B,
    INVESTOR_C,
    SPONSOR,
    TENANT,
    TRUSTEE,
    add_qualified_investor,
    api_client,
    create_capital_need,
    create_subscription,
    create_subscription_payload,
    declare_distribution,
    fund_capital_need,
    list_ledger_entries,
    offering_version,
    read_capital_need,
    read_distribution,
    read_exchange_file,
    read_investor,
    read_offering,
    read_trust,
    set_clock,
    setup_funding_with_investor_a,
    setup_operating_trust,
    setup_trust_funding,
    trust_version,
    validate_error,
    validate_paginated,
    validate_success,
)

INVESTOR_D = {
    "legal_name": "Delta Ridge Holdings",
    "entity_type": "INDIVIDUAL",
    "accreditation_method": "SELF_CERT_NET_WORTH",
    "annual_income_cents": 90_000_000,
    "net_worth_cents": 2_000_000_000,
    "liquid_net_worth_cents": 1_600_000_000,
}

EXCHANGE_FILE_D = {
    "qi_reference": "QI-D-2026",
    "relinquished_closed_on": "2026-08-05T00:00:00.000Z",
    "relinquished_sale_price_cents": 900_000_000,
    "net_proceeds_cents": 500_000_000,
    "debt_retired_cents": 200_000_000,
    "identification_rule": "THREE_PROPERTY",
    "boot_tolerance_cents": 0,
}


class TestExemptionRuleGatesTheAccreditationMethod:
    def test_a_self_certified_investor_is_refused_on_a_generally_solicited_deal(self):
        """The same offering accepts the investor holding a third-party letter.

        PRD: "Where the offering's `exemption_rule` is `RULE_506C`, the
        investor's `accreditation_method` must be `THIRD_PARTY_LETTER`."

        Design: Corner/validations/self_certified_investor_rejected_under_rule_506c
        """
        deal = setup_trust_funding(offering={"exemption_rule": "RULE_506C"})
        add_qualified_investor(deal, key="investor_a", investor_profile=INVESTOR_A)
        add_qualified_investor(
            deal,
            key="investor_b",
            investor_profile=INVESTOR_B,
            exchange_file=EXCHANGE_FILE_B,
            evidence_reference="CPA-LTR-B-2026",
        )

        refused = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_a"]["id"],
                deal["exchange_file_a"]["id"],
                300,
                offering_version(deal["offering"]["id"]),
            ),
            SPONSOR,
        )
        validate_error(refused, "ERR_ACCREDITATION_METHOD_NOT_PERMITTED", 422)

        investor_a = read_investor(deal["investor_a"]["id"])
        assert investor_a["accreditation_status"] == "VERIFIED"
        assert investor_a["suitability_status"] == "APPROVED"
        assert investor_a["accreditation_method"] == "SELF_CERT_NET_WORTH"

        accepted = validate_success(
            api_client.create_subscription(
                create_subscription_payload(
                    deal["offering"]["id"],
                    deal["investor_b"]["id"],
                    deal["exchange_file_b"]["id"],
                    300,
                    offering_version(deal["offering"]["id"]),
                ),
                SPONSOR,
            ),
            201,
        )
        assert accepted["status"] == "RESERVED"
        assert accepted["investment_amount_cents"] == 300_000_000

        offering = read_offering(deal["offering"]["id"])
        assert offering["exemption_rule"] == "RULE_506C"
        assert offering["units_committed"] == 300


class TestCapacityIsAnAggregateGate:
    def test_three_individually_valid_orders_exceed_the_authorised_units(self):
        """625 units against 620 authorised, refused on the third order alone.

        PRD: "Only a subscription that arrives when the target is *already* met,
        or one that would push committed units past the authorised units, is
        refused with `ERR_OFFERING_OVERSUBSCRIBED`."

        Design: Corner/validations/offering_oversubscribed_when_units_exceed_authorised
        """
        deal = setup_funding_with_investor_a()
        add_qualified_investor(
            deal,
            key="investor_b",
            investor_profile=INVESTOR_B,
            exchange_file=EXCHANGE_FILE_B,
            evidence_reference="CPA-LTR-B-2026",
        )
        add_qualified_investor(
            deal,
            key="investor_c",
            investor_profile=INVESTOR_C,
            exchange_file=EXCHANGE_FILE_C,
            evidence_reference="CPA-LTR-C-2026",
        )
        create_subscription(
            deal["offering"]["id"],
            deal["investor_a"]["id"],
            deal["exchange_file_a"]["id"],
            300,
            offering_version(deal["offering"]["id"]),
        )
        create_subscription(
            deal["offering"]["id"],
            deal["investor_b"]["id"],
            deal["exchange_file_b"]["id"],
            300,
            offering_version(deal["offering"]["id"]),
        )

        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 600
        assert offering["min_units_per_investor"] == 15
        assert read_investor(deal["investor_c"]["id"])["suitability_cap_cents"] == (
            140_000_000
        )

        response = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_c"]["id"],
                deal["exchange_file_c"]["id"],
                25,
                offering["version"],
            ),
            SPONSOR,
        )
        validate_error(response, "ERR_OFFERING_OVERSUBSCRIBED", 422)

        unchanged = read_offering(deal["offering"]["id"])
        assert unchanged["units_committed"] == 600
        assert unchanged["equity_committed_cents"] == 600_000_000

        _, meta = validate_paginated(
            api_client.list_subscriptions(
                SPONSOR, params={"offering_id": deal["offering"]["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 2

        trust = read_trust(deal["trust"]["id"])
        assert trust["total_units"] == 620
        assert trust["units_issued"] == 0


class TestBootTolerance:
    def test_a_large_exchange_parked_in_twenty_units_leaves_untolerated_boot(self):
        """The debt share is rounded half up, and the shortfall is all boot.

        PRD: "Boot is the taxable cash the taxpayer fails to reinvest, computed
        as follows: the investor's `debt_share_cents` is the facility's
        `principal_cents` multiplied by the `units_requested` and divided by the
        trust's `total_units`, rounded half up — the only rounded step in the
        whole computation; the replacement value is the `investment_amount_cents`
        plus that debt share; the relinquished value is the exchange file's
        `net_proceeds_cents` plus its `debt_retired_cents`; and `boot_cents` is
        the relinquished value minus the replacement value, or zero when that
        difference would be negative, boot never being negative."

        PRD: "The subscription is refused with `ERR_BOOT_EXCEEDS_TOLERANCE` when
        `boot_cents` exceeds the file's `boot_tolerance_cents`; equality is
        accepted."

        Design: Corner/validations/subscription_boot_above_zero_tolerance_rejected
        """
        deal = setup_trust_funding()
        add_qualified_investor(
            deal,
            key="investor_d",
            investor_profile=INVESTOR_D,
            exchange_file=EXCHANGE_FILE_D,
            evidence_reference="NW-STMT-D-2026",
        )
        assert read_investor(deal["investor_d"]["id"])["suitability_cap_cents"] == (
            359_340_659
        )
        assert deal["exchange_file_d"]["boot_tolerance_cents"] == 0

        response = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_d"]["id"],
                deal["exchange_file_d"]["id"],
                20,
                offering_version(deal["offering"]["id"]),
            ),
            SPONSOR,
        )
        validate_error(response, "ERR_BOOT_EXCEEDS_TOLERANCE", 422)

        _, meta = validate_paginated(
            api_client.list_subscriptions(
                SPONSOR, params={"investor_id": deal["investor_d"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_offering(deal["offering"]["id"])["units_committed"] == 0


class TestExchangeFileOwnership:
    def test_another_investors_file_is_refused_and_the_own_file_is_accepted(self):
        """Three valid entities, one invalid relationship between two of them.

        PRD: "The exchange file belongs to the subscribing investor, on
        subscription creation: `ERR_EXCHANGE_FILE_INVESTOR_MISMATCH`."

        Design: Corner/validations/subscription_with_another_investors_exchange_file_rejected
        """
        deal = setup_funding_with_investor_a()
        add_qualified_investor(
            deal,
            key="investor_b",
            investor_profile=INVESTOR_B,
            exchange_file=EXCHANGE_FILE_B,
            evidence_reference="CPA-LTR-B-2026",
        )
        version_before = offering_version(deal["offering"]["id"])

        mismatched = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_a"]["id"],
                deal["exchange_file_b"]["id"],
                300,
                version_before,
            ),
            SPONSOR,
        )
        validate_error(mismatched, "ERR_EXCHANGE_FILE_INVESTOR_MISMATCH", 422)
        assert deal["exchange_file_b"]["investor_id"] == deal["investor_b"]["id"]

        accepted = validate_success(
            api_client.create_subscription(
                create_subscription_payload(
                    deal["offering"]["id"],
                    deal["investor_a"]["id"],
                    deal["exchange_file_a"]["id"],
                    300,
                    version_before,
                ),
                SPONSOR,
            ),
            201,
        )
        assert accepted["status"] == "RESERVED"
        assert accepted["exchange_file_id"] == deal["exchange_file_a"]["id"]

        assert read_offering(deal["offering"]["id"])["units_committed"] == 300
        assert read_exchange_file(deal["exchange_file_b"]["id"])["status"] == (
            "IDENTIFIED"
        )


class TestDistributionPaymentWaitsForThePeriodToEnd:
    def test_a_period_may_be_declared_early_but_never_paid_early(self):
        """Declaration is a projection; payment is not.

        PRD: "It requires the distribution to be `DECLARED`, the trust to be
        `OPERATING` or `WINDING_DOWN`, the logical clock to be at or after the
        `period_end` — a period may not be paid before it has ended, or
        `ERR_DISTRIBUTION_PERIOD_NOT_ENDED` — and the trust's
        `operating_balance_cents` to be at least the amount about to leave the
        operating bucket, being the `FINAL_CASH` amount plus its reserve
        replenishment."

        Design: Corner/validations/distribution_pay_before_period_end_rejected
        """
        deal = setup_operating_trust()
        set_clock("2027-01-02T00:00:00Z")
        distribution = declare_distribution(
            deal["trust"]["id"],
            trust_version(deal["trust"]["id"]),
            period_start="2027-01-01T00:00:00Z",
            period_end="2027-04-01T00:00:00Z",
        )
        assert distribution["status"] == "DECLARED"

        response = api_client.pay_distribution(distribution["id"], TRUSTEE)
        validate_error(response, "ERR_DISTRIBUTION_PERIOD_NOT_ENDED", 422)

        stored = read_distribution(distribution["id"])
        assert stored["status"] == "DECLARED"
        assert stored["final_amount_cents"] is None
        assert stored["reconciliation_delta_cents"] is None
        assert stored["paid_at"] is None

        _, meta = validate_paginated(
            api_client.list_distribution_allocations(
                TRUSTEE, params={"distribution_id": distribution["id"]}
            )
        )
        assert meta["total_count"] == 0

        trust = read_trust(deal["trust"]["id"])
        assert trust["operating_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["operating_balance_cents"]
        )
        assert trust["reserve_balance_cents"] == (
            CANONICAL_OPERATING_TRUST["reserve_balance_cents"]
        )


class TestReserveIsAHardCeilingNotAnOverdraft:
    def test_a_draw_larger_than_the_reserve_leaves_the_need_identified(self):
        """Forty million of work against a thirty million reserve.

        PRD: "With `funding_source` `RESERVE` the actor must be the `Trustee`,
        the trust must be `OPERATING` with posture exactly `OPEN` — a
        `RESTRICTED` posture blocks reserve draws with `ERR_TRUST_RESTRICTED`,
        precisely because the reserve is already below its floor — the
        `need_type` must not be `STRUCTURAL_CAPEX` (otherwise
        `ERR_STRUCTURAL_CAPEX_PROHIBITED`, structural work being the master
        tenant's burden), and the trust's `reserve_balance_cents` must be at
        least the need's `amount_cents`, or `ERR_RESERVE_INSUFFICIENT`."

        Design: Corner/validations/capital_need_reserve_draw_above_reserve_balance_rejected
        """
        deal = setup_operating_trust()
        need = create_capital_need(
            deal["trust"]["id"],
            need_type="NORMAL_REPAIR",
            amount_cents=40_000_000,
            needed_by="2027-01-31T00:00:00Z",
        )

        response = api_client.fund_capital_need(
            need["id"], {"funding_source": "RESERVE"}, TRUSTEE
        )
        validate_error(response, "ERR_RESERVE_INSUFFICIENT", 422)

        stored = read_capital_need(need["id"])
        assert stored["status"] == "IDENTIFIED"
        assert stored["funding_source"] is None
        assert stored["funded_at"] is None

        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == 30_000_000
        assert trust["posture"] == "OPEN"
        assert list_ledger_entries(
            deal["trust"]["id"], entry_type="RESERVE_DRAW"
        ) == []


class TestMasterTenantFundingSitsOutsideTheBooks:
    def test_a_structural_need_the_reserve_may_not_touch_is_funded_by_the_tenant(self):
        """The prohibition is scoped to the source, not to the need type.

        PRD: "This funding is **outside the trust's books entirely**: no ledger
        entry is written, `reserve_balance_cents` and `operating_balance_cents`
        are both unchanged, and the posture cannot move."

        Design: Corner/validations/structural_capex_funded_by_master_tenant_accepted
        """
        deal = setup_operating_trust()
        need = create_capital_need(
            deal["trust"]["id"],
            need_type="STRUCTURAL_CAPEX",
            amount_cents=80_000_000,
            needed_by="2027-01-31T00:00:00Z",
        )
        entries_before = len(list_ledger_entries(deal["trust"]["id"]))

        funded = fund_capital_need(need["id"], "MASTER_TENANT", headers=TENANT)

        assert funded["status"] == "FUNDED"
        assert funded["funding_source"] == "MASTER_TENANT"
        assert funded["funded_at"] == "2026-11-20T00:00:00.000Z"

        trust = read_trust(deal["trust"]["id"])
        assert trust["reserve_balance_cents"] == 30_000_000
        assert trust["operating_balance_cents"] == 1_098_901
        assert trust["posture"] == "OPEN"
        assert len(list_ledger_entries(deal["trust"]["id"])) == entries_before
