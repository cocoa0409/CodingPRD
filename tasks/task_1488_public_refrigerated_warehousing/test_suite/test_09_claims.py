"""Bailment claims: liability-model settlement variants, appeal loop, filing gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_customer_with_card,
    create_zone,
    decide_claim,
    file_claim,
    get_claim,
    get_excursion,
    get_open_invoice,
    make_customer_admin_headers,
    receive_stock,
    report_excursion,
    confirm_excursion,
    review_claim,
    settle_claim,
    setup_confirmed_excursion,
    setup_stocked_account,
    validate_error,
    validate_success,
)

BILLING = TEST_USERS["billing_admin_headers"]


class TestSettlementLiabilityModels:
    def _setup_two_customer_excursion(self):
        """One confirmed excursion quarantining 4 pallets each of two customers:
        L on LIMITED_LIABILITY (2000/pallet), D on DECLARED_VALUE."""
        cust_l, _card_l = create_customer_with_card("L Ltd")
        cust_d, _card_d = create_customer_with_card(
            "D Decl", liability_model="DECLARED_VALUE")
        zone = create_zone("FZ-2", capacity_pallets=20, dock_doors=2)
        receive_stock(cust_l["id"], zone["id"], 4, product_code="SHRIMP",
                      lot_code="SL1", window_start="2026-08-02T08:00:00Z",
                      window_end="2026-08-02T10:00:00Z")
        receive_stock(cust_d["id"], zone["id"], 4, product_code="SHRIMP",
                      lot_code="SL1", window_start="2026-08-02T11:00:00Z",
                      window_end="2026-08-02T13:00:00Z")
        excursion = report_excursion(zone["id"], observed_temp_c=-5.5,
                                     window_start="2026-08-03T00:00:00Z",
                                     window_end="2026-08-04T00:00:00Z")
        confirm_excursion(excursion["id"])
        return cust_l, cust_d, excursion

    def test_limited_liability_caps_settlement(self, api):
        """PRD §3.8: "Under `LIMITED_LIABILITY`, the settlement is the lesser of
        `declared_value_cents` and the `affected_pallet_count` multiplied by the
        card's `liability_per_pallet_cents` — strictly less than the declared
        value whenever the declared value exceeds that per-pallet cap times the
        affected count."

        Design: Difficulty/dual_variant_calc/claim_settlement_declared_value_vs_limited_liability
        """
        cust_l, _cust_d, excursion = self._setup_two_customer_excursion()
        claim = file_claim(cust_l["id"], excursion["id"], affected_pallet_count=4,
                           declared_value_cents=50000)
        review_claim(claim["id"])
        decide_claim(claim["id"], "APPROVED")
        after = get_claim(claim["id"])
        assert after["status"] == "APPROVED"
        assert after["settlement_cents"] == 8000, (
            f"min(50000, 4 * 2000) == 8000, got {after['settlement_cents']}")

    def test_declared_value_pays_in_full(self, api):
        """PRD §3.8: "Under `DECLARED_VALUE`, the settlement is the full
        `declared_value_cents`."
        PRD §3.6: "the count of pallets caught is stored on the excursion as
        `quarantined_pallet_count`."

        Design: Difficulty/dual_variant_calc/claim_settlement_declared_value_vs_limited_liability
        """
        cust_l, cust_d, excursion = self._setup_two_customer_excursion()
        assert get_excursion(excursion["id"])["quarantined_pallet_count"] == 8, (
            "both customers' 4 pallets quarantined by the same breach")
        claim = file_claim(cust_d["id"], excursion["id"], affected_pallet_count=4,
                           declared_value_cents=50000)
        review_claim(claim["id"])
        decide_claim(claim["id"], "APPROVED")
        after = get_claim(claim["id"])
        assert after["settlement_cents"] == 50000, (
            f"DECLARED_VALUE pays the declared value in full, got "
            f"{after['settlement_cents']}")
        # Same loss data, different liability model -> different settlement.
        claim_l = file_claim(cust_l["id"], excursion["id"],
                             affected_pallet_count=4, declared_value_cents=50000)
        review_claim(claim_l["id"])
        decide_claim(claim_l["id"], "APPROVED")
        assert get_claim(claim_l["id"])["settlement_cents"] != 50000


class TestClaimAppealLoop:
    def _setup_filed_claim(self):
        sc = setup_stocked_account(customer_name="Claim Co", zone_code="FZ-8",
                                   pallets=2)
        setup_confirmed_excursion(sc, observed_temp_c=-1.0)
        claim = file_claim(sc["customer"]["id"], sc["excursion"]["id"],
                           affected_pallet_count=2, declared_value_cents=10000)
        review_claim(claim["id"])
        decide_claim(claim["id"], "DENIED")
        return sc, claim

    def test_denied_reopened_approved_cycle(self, api):
        """PRD §3.8: "The appeal loop runs through the customer: the owning
        `CustomerAdmin` may reopen a `DENIED` claim, moving it to `REOPENED`, from
        which a `ClaimsAdjuster`'s review returns it to `UNDER_REVIEW` for another
        decision."
        PRD §3.8: "Under `LIMITED_LIABILITY`, the settlement is the lesser of
        `declared_value_cents` and the `affected_pallet_count` multiplied by the
        card's `liability_per_pallet_cents`"

        Design: Difficulty/non_linear_state_machine/claim_denied_reopened_approved_cycle
        """
        sc, claim = self._setup_filed_claim()
        assert get_claim(claim["id"])["status"] == "DENIED"
        reopened = validate_success(
            api.reopen_claim(
                claim["id"], make_customer_admin_headers(sc["customer"]["id"])))
        assert reopened["status"] == "REOPENED"
        review_claim(claim["id"])
        decided = decide_claim(claim["id"], "APPROVED")
        assert decided["status"] == "APPROVED"
        assert decided["settlement_cents"] == 4000, (
            f"min(10000, 2 * 2000) == 4000, got {decided['settlement_cents']}")
        settled = settle_claim(claim["id"])
        assert settled["status"] == "SETTLED"

    def test_settlement_credits_open_invoice_negative_total_allowed(self, api):
        """PRD §3.8: "Settlement belongs to a `BillingAdmin`: settling an
        `APPROVED` claim moves it to `SETTLED` and credits its `settlement_cents`
        into the customer's `OPEN` invoice under `claim_credit_cents`, recomputing
        the invoice's `total_cents`."
        PRD §2.6: "An invoice total is then a plain sum of integer-cent components
        with no further rounding, and it is permitted to go negative when claim
        credits exceed charges, representing a credit balance owed to the
        customer; the total is never clamped at zero."

        Design: Difficulty/non_linear_state_machine/claim_denied_reopened_approved_cycle
        """
        sc, claim = self._setup_filed_claim()
        validate_success(
            api.reopen_claim(
                claim["id"], make_customer_admin_headers(sc["customer"]["id"])))
        review_claim(claim["id"])
        decide_claim(claim["id"], "APPROVED")
        settle_claim(claim["id"])
        invoice = get_open_invoice(sc["customer"]["id"])
        assert invoice["claim_credit_cents"] == 4000
        # handling_in 2*1000 = 2000 accrued; total = 2000 - 4000 == -2000.
        assert invoice["handling_in_cents"] == 2000
        assert invoice["total_cents"] == -2000, (
            "a credit balance owed to the customer is never clamped at zero")


class TestClaimExceedsQuarantinedCount:
    def test_affected_count_above_quarantined_rejected(self, api):
        """PRD §3.8: "Two cross-reference gates apply at filing: the excursion
        must stand at `CONFIRMED_BREACH`, else `ERR_EXCURSION_NOT_CONFIRMED`; and
        the `affected_pallet_count` must not exceed that excursion's
        `quarantined_pallet_count`, else `ERR_CLAIM_EXCEEDS_QUARANTINED_COUNT`
        with HTTP status 422."

        Design: Corner/validations/claim_exceeds_quarantined_count_rejected
        """
        sc = setup_stocked_account(customer_name="Exceed Co", zone_code="FZ-XC",
                                   capacity_pallets=5, pallets=2)
        setup_confirmed_excursion(sc, observed_temp_c=-2.0)
        assert sc["excursion"]["quarantined_pallet_count"] == 2
        resp = api.create_claim(
            {"customer_id": sc["customer"]["id"],
             "excursion_id": sc["excursion"]["id"], "affected_pallet_count": 5,
             "declared_value_cents": 9000},
            make_customer_admin_headers(sc["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_QUARANTINED_COUNT,
                       expected_status=422)
