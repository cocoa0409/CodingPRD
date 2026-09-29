"""Seat-credit purchase settlement and the dram-shop premium credit.

Both computations pin an evaluation order whose reordering would produce different money,
so each test observes the pinned order through the cents it lands on.
"""
from test_helpers import (
    CLOCK_DOCUMENTATION,
    assert_dram_shop_document,
    assert_employer_account,
    assert_same_instant,
    assert_seat_credit_ledger,
    create_employer_account,
    get_account,
    issue_dram_shop_document,
    list_dram_shop_documents_for,
    make_employer_admin_headers,
    seat_credit_purchase_payload,
    set_clock,
    setup_certified_server_at_location,
    validate_success,
)


class TestSeatCreditSettlement:
    def test_eighty_seat_purchase_takes_gross_tier_capped_fee_and_net_based_bonus(self, api):
        """PRD §3.8: "The volume discount percentage is chosen from the **gross** subtotal,
        never the net: 0.00 below five hundred dollars, 3.00 from five hundred dollars up to
        but excluding fifteen hundred dollars, 6.00 from fifteen hundred dollars up to but
        excluding five thousand dollars, and 10.00 at five thousand dollars and above."
        PRD §3.8: "The processing fee is the smaller of a twenty-five-dollar cap and 2.9
        percent of the net rounded half up to whole cents."
        PRD §3.8: "Bonus credits are the net divided by one thousand dollars, rounded
        **down** to a whole number — one extra seat per full thousand dollars of net charge."
        PRD §3.8: "The account then absorbs the result: `seat_credits_purchased_total` and
        `seat_credit_balance` each rise by the seats granted, `last_purchase_discount_pct`
        records the volume discount percentage from step two,
        `last_purchase_total_charged_cents` records the step-six total, and
        `lifetime_charged_cents` accumulates that total across every purchase."

        Design: Difficulty/combinatorial_formula/seat_credit_settlement_pinned_eight_step_order_with_fee_cap_and_net_based_bonus
        """
        account = create_employer_account()
        employer_headers = make_employer_admin_headers(account["id"])

        response = api.purchase_seat_credits(
            account["id"], seat_credit_purchase_payload(80, 2500), employer_headers)
        updated = validate_success(response, 200)
        assert_employer_account(updated)

        assert updated["last_purchase_discount_pct"] == 6.00, (
            "gross subtotal 200000 cents sits in the 6.00 band, got "
            f"{updated['last_purchase_discount_pct']}")
        assert updated["last_purchase_total_charged_cents"] == 190500, (
            "net 188000 plus the capped fee 2500 is 190500, got "
            f"{updated['last_purchase_total_charged_cents']}")
        assert updated["seat_credits_purchased_total"] == 81, (
            "80 seats plus one net-based bonus seat, not two, got "
            f"{updated['seat_credits_purchased_total']}")
        assert updated["seat_credit_balance"] == 81
        assert updated["lifetime_charged_cents"] == 190500

    def test_five_hundred_dollar_gross_takes_the_lower_tier_and_grants_no_bonus(self, api):
        """PRD §3.8: "The volume discount percentage is chosen from the **gross** subtotal,
        never the net: 0.00 below five hundred dollars, 3.00 from five hundred dollars up to
        but excluding fifteen hundred dollars, 6.00 from fifteen hundred dollars up to but
        excluding five thousand dollars, and 10.00 at five thousand dollars and above."
        PRD §3.8: "The processing fee is the smaller of a twenty-five-dollar cap and 2.9
        percent of the net rounded half up to whole cents."
        PRD §3.8: "Bonus credits are the net divided by one thousand dollars, rounded
        **down** to a whole number — one extra seat per full thousand dollars of net charge."
        PRD §3.8: "The seat-credit ledger is an identity that must hold at all times:
        `seat_credit_balance` equals `seat_credits_purchased_total` minus
        `seat_credits_consumed_total` plus `seat_credits_refunded_total`."

        Design: Difficulty/combinatorial_formula/seat_credit_settlement_pinned_eight_step_order_with_fee_cap_and_net_based_bonus
        """
        account = create_employer_account()
        employer_headers = make_employer_admin_headers(account["id"])

        validate_success(api.purchase_seat_credits(
            account["id"], seat_credit_purchase_payload(80, 2500), employer_headers), 200)
        second = validate_success(api.purchase_seat_credits(
            account["id"], seat_credit_purchase_payload(20, 2500), employer_headers), 200)

        assert second["last_purchase_discount_pct"] == 3.00, (
            "a gross subtotal of exactly 50000 cents is inside the 3.00 band, got "
            f"{second['last_purchase_discount_pct']}")
        assert second["last_purchase_total_charged_cents"] == 49907, (
            "net 48500 plus the uncapped fee 1407 is 49907, got "
            f"{second['last_purchase_total_charged_cents']}")
        assert second["seat_credits_purchased_total"] == 101, (
            "20 seats plus zero bonus on top of the earlier 81, got "
            f"{second['seat_credits_purchased_total']}")
        assert second["seat_credit_balance"] == 101
        assert second["lifetime_charged_cents"] == 240407, (
            "190500 plus 49907 accumulates to 240407, got "
            f"{second['lifetime_charged_cents']}")
        assert second["seat_credits_consumed_total"] == 0
        assert second["seat_credits_refunded_total"] == 0
        assert_seat_credit_ledger(second)


class TestDramShopPremiumCredit:
    def test_premium_credit_rounds_each_location_before_summing(self, api):
        """PRD §3.9: "Walking the account's locations in ascending `created_at`, each
        location's own credit is `annual_premium_cents` multiplied by `discount_pct` divided
        by 100, rounded half up to whole cents; those already-rounded per-location values are
        summed into `discount_credit_cents`."
        PRD §3.9: "Summing the premiums first and rounding once at the end is wrong and can
        differ by a cent or more."
        PRD §3.9: "Every location of the account participates regardless of `premise_type`,
        `training_requirement` or assignment count, and the document's own `location_count`
        records how many locations went into the computation."
        PRD §3.9: "The base tier is chosen from the account's stored strict rate: 98.00 or
        above is `TIER_3` with a base of 10.00 percent, 90.00 or above is `TIER_2` with a
        base of 7.00, and 80.00 or above is `TIER_1` with a base of 4.00."
        PRD §3.9: "The multi-location bonus is 2.00 percentage points, awarded only when the
        account's `location_count` is at least 3 **and** the smallest
        `compliance_rate_strict_pct` across all of the account's locations is at least 90.00;
        locations with no live assignment contribute 100.00 to that minimum, so they never
        drag it down."

        Design: Difficulty/combinatorial_formula/dram_shop_credit_rounds_per_location_before_summing
        """
        scenario = setup_certified_server_at_location(location_specs=[
            {"location_name": "Alamo Taproom", "annual_premium_cents": 4821734},
            {"location_name": "Riverwalk Cantina", "annual_premium_cents": 1257444},
        ])
        set_clock(CLOCK_DOCUMENTATION)

        document = issue_dram_shop_document(scenario["account"]["id"],
                                            headers=scenario["employer_headers"])
        assert_dram_shop_document(document)

        assert document["strict_compliance_rate_pct"] == 100.00
        assert document["discount_tier"] == "TIER_3"
        assert document["discount_pct"] == 10.00, (
            "base 10.00 with no tenure and no multi-location bonus at two locations, got "
            f"{document['discount_pct']}")
        assert document["months_documented"] == 0
        assert document["location_count"] == 2
        assert document["discount_credit_cents"] == 607917, (
            "482173 plus 125744 is 607917; summing the premiums first would give 607918, got "
            f"{document['discount_credit_cents']}")
        assert document["document_state"] == "ISSUED"
        assert document["void_reason"] is None

    def test_first_issuance_documents_the_account_and_anchors_the_tenure_clock(self, api):
        """PRD §3.9: "On issuance, `snapshot_at` is stamped from the logical clock,
        `strict_compliance_rate_pct` snapshots the account's `account_compliance_rate_pct`,
        and `months_documented` is the number of whole months between the account's
        `first_documented_at` and `snapshot_at` — zero for the account's very first document,
        since there is no earlier anchor."
        PRD §3.9: "The account's `dram_shop_discount_status` becomes `DOCUMENTED`,
        `first_documented_at` is set on the first issuance only, and the account's `version`
        increments."

        Design: Difficulty/combinatorial_formula/dram_shop_credit_rounds_per_location_before_summing
        """
        scenario = setup_certified_server_at_location(location_specs=[
            {"location_name": "Alamo Taproom", "annual_premium_cents": 4821734},
            {"location_name": "Riverwalk Cantina", "annual_premium_cents": 1257444},
        ])
        set_clock(CLOCK_DOCUMENTATION)
        version_before = get_account(scenario["account"]["id"])["version"]

        document = issue_dram_shop_document(scenario["account"]["id"],
                                            headers=scenario["employer_headers"])
        assert_same_instant(document["snapshot_at"], CLOCK_DOCUMENTATION, "snapshot_at")

        account = get_account(scenario["account"]["id"])
        assert account["dram_shop_discount_status"] == "DOCUMENTED"
        assert_same_instant(account["first_documented_at"], CLOCK_DOCUMENTATION,
                            "first_documented_at")
        assert account["version"] > version_before, (
            "issuance increments the account's version, got "
            f"{account['version']} against {version_before}")

    def test_discount_pct_clamps_at_twelve_when_the_bonuses_overflow(self, api):
        """PRD §3.9: "The tenure bonus rewards continuous documentation: it is one percentage
        point for each full twelve months of `months_documented`, taking the whole number of
        complete years, capped at 3.00 percentage points."
        PRD §3.9: "The multi-location bonus is 2.00 percentage points, awarded only when the
        account's `location_count` is at least 3 **and** the smallest
        `compliance_rate_strict_pct` across all of the account's locations is at least 90.00;
        locations with no live assignment contribute 100.00 to that minimum, so they never
        drag it down."
        PRD §3.9: "The three components are added, floored at 0.00, capped at 12.00, and the
        result is rounded half up to two decimals exactly once after that clamping — that
        value is `discount_pct` and the chosen tier is `discount_tier`."

        Design: Difficulty/combinatorial_formula/dram_shop_discount_pct_cap_binds_over_tenure_and_multi_location_bonuses
        """
        scenario = setup_certified_server_at_location(location_specs=[
            {"location_name": "Alamo Taproom", "annual_premium_cents": 4821734},
            {"location_name": "Riverwalk Cantina", "annual_premium_cents": 1257444},
        ])
        set_clock(CLOCK_DOCUMENTATION)
        issue_dram_shop_document(scenario["account"]["id"],
                                 headers=scenario["employer_headers"])

        validate_success(api.create_employer_location(
            scenario["account"]["id"],
            {"location_name": "Hill Country Icehouse",
             "state_jurisdiction_id": scenario["jurisdiction"]["id"],
             "premise_type": "ON_PREMISE",
             "annual_premium_cents": 999920},
            scenario["employer_headers"]), 201)
        set_clock("2027-09-16T09:00:00Z")

        second = issue_dram_shop_document(
            scenario["account"]["id"], headers=scenario["employer_headers"],
            insurer_name="Brazos Mutual Casualty", policy_number="DS-2027-88220",
            coverage_period_start="2027-10-01T00:00:00Z",
            coverage_period_end="2028-10-01T00:00:00Z")

        assert second["months_documented"] == 13, (
            "thirteen whole months separate 2026-08-15T09:00:00Z from 2027-09-16T09:00:00Z, "
            f"got {second['months_documented']}")
        assert second["discount_tier"] == "TIER_3"
        assert second["discount_pct"] == 12.00, (
            "10.00 base plus 1.00 tenure plus 2.00 multi-location is 13.00 and clamps to "
            f"12.00, got {second['discount_pct']}")
        assert second["location_count"] == 3
        assert second["discount_credit_cents"] == 849491, (
            "578608 plus 150893 plus 119990 is 849491, got "
            f"{second['discount_credit_cents']}")
        assert second["strict_compliance_rate_pct"] == 100.00

    def test_second_issuance_supersedes_the_first_and_leaves_the_anchor_alone(self, api):
        """PRD §3.9: "Any prior document of this account still in `ISSUED` moves to
        `SUPERSEDED`."
        PRD §3.9: "The account's `dram_shop_discount_status` becomes `DOCUMENTED`,
        `first_documented_at` is set on the first issuance only, and the account's `version`
        increments."

        Design: Difficulty/combinatorial_formula/dram_shop_discount_pct_cap_binds_over_tenure_and_multi_location_bonuses
        """
        scenario = setup_certified_server_at_location(location_specs=[
            {"location_name": "Alamo Taproom", "annual_premium_cents": 4821734},
            {"location_name": "Riverwalk Cantina", "annual_premium_cents": 1257444},
        ])
        set_clock(CLOCK_DOCUMENTATION)
        first = issue_dram_shop_document(scenario["account"]["id"],
                                        headers=scenario["employer_headers"])

        validate_success(api.create_employer_location(
            scenario["account"]["id"],
            {"location_name": "Hill Country Icehouse",
             "state_jurisdiction_id": scenario["jurisdiction"]["id"],
             "premise_type": "ON_PREMISE",
             "annual_premium_cents": 999920},
            scenario["employer_headers"]), 201)
        set_clock("2027-09-16T09:00:00Z")
        issue_dram_shop_document(
            scenario["account"]["id"], headers=scenario["employer_headers"],
            policy_number="DS-2027-88220",
            coverage_period_start="2027-10-01T00:00:00Z",
            coverage_period_end="2028-10-01T00:00:00Z")

        documents = list_dram_shop_documents_for(scenario["account"]["id"])
        superseded = [d for d in documents if d["id"] == first["id"]][0]
        assert superseded["document_state"] == "SUPERSEDED", (
            "the prior ISSUED document moves to SUPERSEDED, got "
            f"{superseded['document_state']}")

        account = get_account(scenario["account"]["id"])
        assert account["dram_shop_discount_status"] == "DOCUMENTED"
        assert_same_instant(account["first_documented_at"], CLOCK_DOCUMENTATION,
                            "first_documented_at")
        assert account["location_count"] == 3
