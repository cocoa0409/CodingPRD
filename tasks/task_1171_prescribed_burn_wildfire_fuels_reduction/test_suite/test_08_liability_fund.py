"""Liability adjudication variants, fund payout cap, and the compensating ledger
(PRD §2.10, §3.9)."""
from test_helpers import (
    ANY_READER_HEADERS,
    TEST_USERS,
    ApiErrorId,
    adjudicate_payload,
    assess_costs_payload,
    create_incident_payload,
    get_success_data,
    setup_adjudicated_claim_ctx,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COMMANDER = TEST_USERS["commander_headers"]


class TestSuppressionAllocationVariants:
    def test_suppression_allocation_standard(self, api):
        """PRD §3.9: "Under the standard allocation — `negligence_found` false —
        `landowner_share_cents` is the smaller of the escaped acreage times 25,000 cents
        per acre and the association's `landowner_liability_cap_cents`."
        PRD §3.9: "In both variants `association_share_cents` is the
        `total_suppression_cost_cents` minus the landowner share."

        Design: Difficulty/dual_variant_calc/suppression_allocation_standard_vs_negligence
        """
        ctx = setup_adjudicated_claim_ctx(outcome="ASSOCIATION_LIABLE", negligence=False,
                                          cost=3_000_000, acres=60)
        claim = ctx["claim"]
        # min(60 * 25000, 1_000_000) = 1_000_000
        assert claim["landowner_share_cents"] == 1_000_000
        assert claim["association_share_cents"] == 2_000_000
        assert claim["status"] == "ADJUDICATED"
        landowner = validate_success(
            api.get_landowner(ctx["landowner"]["id"], ANY_READER_HEADERS), 200)
        assert landowner["outstanding_liability_cents"] == 0  # ASSOCIATION_LIABLE adds none

    def test_suppression_allocation_negligence(self, api):
        """PRD §3.9: "Under the negligence allocation — `negligence_found` true — the
        landowner share is the escaped acreage times 25,000 cents times 1.5, rounded
        half-up to a whole cent, with no cap."
        PRD §3.9: "A `LANDOWNER_LIABLE` outcome additionally adds the landowner share to
        the landowner's `outstanding_liability_cents`"

        Design: Difficulty/dual_variant_calc/suppression_allocation_standard_vs_negligence
        """
        ctx = setup_adjudicated_claim_ctx(outcome="LANDOWNER_LIABLE", negligence=True,
                                          cost=3_000_000, acres=60)
        claim = ctx["claim"]
        # round_half_up(60 * 25000 * 1.5) = 2_250_000, uncapped (cap is 1_000_000)
        assert claim["landowner_share_cents"] == 2_250_000
        assert claim["association_share_cents"] == 750_000
        landowner = validate_success(
            api.get_landowner(ctx["landowner"]["id"], ANY_READER_HEADERS), 200)
        assert landowner["outstanding_liability_cents"] == 2_250_000


class TestFundPayoutCap:
    def test_fund_payout_cap_uses_pre_debit_balance(self, api):
        """PRD §3.9: "The payout is computed against the fund balance **before** any
        debit: take that pre-debit balance, halve it and round down to a whole cent, take
        the smaller of that figure and the association's `single_claim_cap_cents` as the
        per-claim ceiling, and set `fund_payout_cents` to the smaller of the claim's
        `association_share_cents` and that ceiling. Using the post-debit balance anywhere
        in this computation is forbidden."

        Design: Difficulty/combinatorial_formula/fund_payout_cap_uses_pre_debit_balance
        """
        ctx = setup_adjudicated_claim_ctx(fund=600_000, outcome="ASSOCIATION_LIABLE",
                                          negligence=False, cost=3_000_000, acres=60)
        # ceiling = min(floor(600000 * 0.5), 500000) = 300000; payout = min(2000000, 300000)
        paid = validate_success(api.pay_claim(ctx["claim"]["id"], ADMIN), 200)
        assert paid["fund_payout_cents"] == 300_000
        assert paid["status"] == "PAID"
        assoc = validate_success(api.get_association(ctx["assoc"]["id"], ANY_READER_HEADERS), 200)
        assert assoc["fund_balance_cents"] == 300_000  # 600000 - 300000

    def test_fund_payout_cap_tracks_live_pre_debit_balance(self, api):
        """PRD §3.9: "The payout is computed against the fund balance **before** any
        debit: take that pre-debit balance, halve it and round down to a whole cent"

        Design: Difficulty/combinatorial_formula/fund_payout_cap_uses_pre_debit_balance
        """
        ctx = setup_adjudicated_claim_ctx(fund=600_000, outcome="ASSOCIATION_LIABLE",
                                          negligence=False, cost=3_000_000, acres=60)
        paid = validate_success(api.pay_claim(ctx["claim"]["id"], ADMIN), 200)
        assert paid["fund_payout_cents"] == 300_000
        # A second assessed incident on the ESCAPED execution, adjudicated identically
        incident2 = validate_success(api.report_incident(
            ctx["execution"]["id"], create_incident_payload(incident_type="SPOT"),
            COMMANDER), 201)
        get_success_data(api.confirm_incident(incident2["id"], COMMANDER))
        get_success_data(api.mark_incident_contained(incident2["id"], COMMANDER))
        get_success_data(api.close_incident(incident2["id"], COMMANDER))
        get_success_data(api.assess_incident_costs(incident2["id"], assess_costs_payload(), COMMANDER))
        claim2 = get_success_data(api.create_liability_claim(incident2["id"], {}, COMMANDER))
        get_success_data(api.begin_claim_investigation(claim2["id"], ADMIN))
        get_success_data(api.adjudicate_claim(
            claim2["id"], adjudicate_payload("ASSOCIATION_LIABLE", False), ADMIN))
        # ceiling recomputed on the live pre-debit balance: floor(300000*0.5) = 150000
        paid2 = validate_success(api.pay_claim(claim2["id"], ADMIN), 200)
        assert paid2["fund_payout_cents"] == 150_000
        assoc = validate_success(api.get_association(ctx["assoc"]["id"], ANY_READER_HEADERS), 200)
        assert assoc["fund_balance_cents"] == 150_000  # 300000 - 150000


class TestPayAndReverseCompensation:
    def test_fund_payout_debits_fund_and_settles_incident(self, api):
        """PRD §3.9: "A successful payment debits the fund by `fund_payout_cents`, moves
        the claim to `PAID`, and settles the incident's billing to `SETTLED`."

        Design: Difficulty/compensating_invariant/fund_payout_then_reversal_restores_balance_exactly
        """
        ctx = setup_adjudicated_claim_ctx(outcome="ASSOCIATION_LIABLE", negligence=False,
                                          cost=3_000_000, acres=60)
        # ceiling = min(floor(10000000*0.5), 500000) = 500000; payout = min(2000000, 500000)
        paid = validate_success(api.pay_claim(ctx["claim"]["id"], ADMIN), 200)
        assert paid["fund_payout_cents"] == 500_000
        assert paid["status"] == "PAID"
        assoc = validate_success(api.get_association(ctx["assoc"]["id"], ANY_READER_HEADERS), 200)
        assert assoc["fund_balance_cents"] == 9_500_000
        incident = validate_success(api.get_incident(ctx["incident"]["id"], ANY_READER_HEADERS), 200)
        assert incident["billing_status"] == "SETTLED"

    def test_reversal_restores_balance_exactly(self, api):
        """PRD §3.9: "Reversing requires `PAID` (`ERR_CLAIM_NOT_PAID`), credits the fund
        by exactly the claim's recorded `fund_payout_cents` — restoring the balance to
        precisely its pre-payment value, per the ledger invariant of §2.10 — moves the
        claim to `PAYMENT_REVERSED`, and disputes the incident's billing to `DISPUTED`."

        Design: Difficulty/compensating_invariant/fund_payout_then_reversal_restores_balance_exactly
        """
        ctx = setup_adjudicated_claim_ctx(outcome="ASSOCIATION_LIABLE", negligence=False,
                                          cost=3_000_000, acres=60)
        validate_success(api.pay_claim(ctx["claim"]["id"], ADMIN), 200)
        reversed_claim = validate_success(
            api.reverse_claim_payment(ctx["claim"]["id"], ADMIN), 200)
        assert reversed_claim["status"] == "PAYMENT_REVERSED"
        assoc = validate_success(api.get_association(ctx["assoc"]["id"], ANY_READER_HEADERS), 200)
        assert assoc["fund_balance_cents"] == 10_000_000  # exact restoration
        incident = validate_success(api.get_incident(ctx["incident"]["id"], ANY_READER_HEADERS), 200)
        assert incident["billing_status"] == "DISPUTED"
