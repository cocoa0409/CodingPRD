"""Calculation correctness: dual-variant raised figures, soft-credit splits,
installment schedules, giving tiers, deductibles, receipt numbering, and match
amounts.

Difficulty queue: dual_variant_calc, combinatorial_formula (installments),
boundary_precision_check. Corner queue: calculations section.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS, ApiErrorId,
    create_open_campaign, create_donor, create_employer, create_household,
    setup_household_with_members, create_acknowledged_gift, record_gift,
    acknowledge_gift, setup_open_campaign_with_donor, create_pledge,
    get_installments_sorted, open_match_claim, approve_match_claim,
    pay_match_claim, receipt_number, rows_of,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


# ---------------------------------------------------------------------------
# Difficulty Rule 1 — dual-variant calculations across entity domains
# ---------------------------------------------------------------------------
class TestDualVariantRaised:
    def test_campaign_raised_hard_vs_with_match_diverge(self, api):
        """PRD §2.7: "the matched amount ... adds it to the gift's campaign's
        `raised_with_match_cents`, whereas denial touches no totals." PRD §3.1:
        "both of its raised figures — `raised_hard_cents` and
        `raised_with_match_cents` — initialized to zero." PRD §3.6: "Paying is the
        divergent branch: it pins the claim's `matched_amount_cents` and adds it to
        the gift's campaign's `raised_with_match_cents`, whereas denial touches no
        totals."

        Design: Difficulty/dual_variant_calc/campaign_raised_hard_vs_with_match
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=1.0, min_gift_cents=2500,
                              max_match_cents=1000000, annual_match_cap_cents=5000000)
        donor = create_donor(employer_id=emp["id"])
        # Two acknowledged gifts of 100000 each.
        _, g1 = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        _, g2 = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        # One match claim PAID at 100000.
        claim = open_match_claim(g1)
        approve_match_claim(claim["id"])
        pay_match_claim(claim["id"])

        data = validate_success(api.get_campaign(camp["id"], CM))
        assert data["raised_hard_cents"] == 200000, \
            f"hard credit of two 100000 gifts must be 200000, got {data['raised_hard_cents']}"
        assert data["raised_with_match_cents"] == 300000, \
            f"hard + 100000 paid match must be 300000, got {data['raised_with_match_cents']}"

    def test_campaign_raised_with_match_includes_only_paid(self, api):
        """PRD §3.6: "Only `PAID` claims consume the annual cap; `SUBMITTED`,
        `APPROVED`, and `DENIED` claims do not." PRD §3.6: "Paying is the divergent
        branch: it pins the claim's `matched_amount_cents` and adds it to the gift's
        campaign's `raised_with_match_cents`, whereas denial touches no totals."

        Before paying, with-match equals hard; only the pay step diverges them.

        Design: Difficulty/dual_variant_calc/campaign_raised_hard_vs_with_match
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=1.0)
        donor = create_donor(employer_id=emp["id"])
        _, g1 = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        claim = open_match_claim(g1)
        approve_match_claim(claim["id"])  # APPROVED but not yet PAID

        data = validate_success(api.get_campaign(camp["id"], CM))
        assert data["raised_hard_cents"] == 100000
        assert data["raised_with_match_cents"] == 100000, \
            "an APPROVED (not PAID) claim must not move raised_with_match_cents"

    def test_donor_lifetime_vs_household_soft_credit_diverge(self, api):
        """PRD §3.4: "A donor's `lifetime_hard_credit_cents` is the sum of
        `amount_cents` over that donor's gifts whose `status` is either
        `ACKNOWLEDGED` or `RECEIPTED`." PRD §3.2: "Under the `FULL_TO_ALL` policy,
        each other member is credited the full gift amount ... so the household total
        grows by the gift amount multiplied by one less than the member count."

        Design: Difficulty/dual_variant_calc/donor_lifetime_vs_household_soft_credit
        """
        hh, donors = setup_household_with_members(policy="FULL_TO_ALL", member_count=3)
        giver = donors[0]
        camp = create_open_campaign(goal_cents=500000)
        create_acknowledged_gift(camp["id"], giver["id"], amount_cents=10000)

        donor_data = validate_success(api.get_donor(giver["id"], GA))
        hh_data = validate_success(api.get_household(hh["id"], CM))
        assert donor_data["lifetime_hard_credit_cents"] == 10000, \
            "single-donor hard credit must equal the 10000 gift"
        assert hh_data["total_soft_credit_cents"] == 20000, \
            "FULL_TO_ALL across two other members yields 10000*2 == 20000 soft credit"

    def test_household_soft_credit_full_to_all_per_member_amount(self, api):
        """PRD §3.2: "a soft-credit row is created for every other member with
        `soft_credit_cents` equal to the gift's `amount_cents`".

        Design: Difficulty/dual_variant_calc/donor_lifetime_vs_household_soft_credit
        """
        hh, donors = setup_household_with_members(policy="FULL_TO_ALL", member_count=3)
        giver = donors[0]
        camp = create_open_campaign(goal_cents=500000)
        _, gift_id = create_acknowledged_gift(camp["id"], giver["id"], amount_cents=10000)

        data, _ = _list(api.list_gift_soft_credits(gift_id, GA, params={"limit": 100}))
        assert len(data) == 2, "FULL_TO_ALL mints one row per OTHER member (2)"
        for row in data:
            assert row["soft_credit_cents"] == 10000, "each other member gets the full gift"
            assert row["beneficiary_donor_id"] != giver["id"], "giver gets no soft-credit row"


# ---------------------------------------------------------------------------
# Difficulty Rule 2 (mode b) — installment schedule remainder rounding order
# ---------------------------------------------------------------------------
class TestInstallmentSchedule:
    def test_front_loaded_remainder_on_first(self, api):
        """PRD §3.5: "Under `FRONT_LOADED`, the earliest installments absorb the
        leftover: each of the first *remainder* installments (those whose
        `sequence_no` is at most the remainder) carries one cent above the base, and
        the rest carry the base."

        Design: Difficulty/combinatorial_formula/installment_schedule_remainder_rounding_order
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=3, frequency="MONTHLY",
                               schedule_basis="FRONT_LOADED")
        amounts = [i["amount_cents"] for i in get_installments_sorted(pledge["id"])]
        assert amounts == [3334, 3333, 3333], f"FRONT_LOADED 10000/3 -> [3334,3333,3333], got {amounts}"
        assert sum(amounts) == 10000, "installment amounts must sum to total exactly"

    def test_front_loaded_sum_conserved_uneven(self, api):
        """PRD §3.5: "Either way the installment amounts sum to `total_amount_cents`
        exactly; the only difference is whether installment 1 or installment *n* is
        the one that may run a cent higher."

        Design: Difficulty/combinatorial_formula/installment_schedule_remainder_rounding_order
        """
        camp, donor = setup_open_campaign_with_donor()
        # 10003 / 4 = base 2500 rem 3 -> [2501,2501,2501,2500] front-loaded.
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10003,
                               installment_count=4, frequency="MONTHLY",
                               schedule_basis="FRONT_LOADED")
        amounts = [i["amount_cents"] for i in get_installments_sorted(pledge["id"])]
        assert amounts == [2501, 2501, 2501, 2500], f"got {amounts}"
        assert sum(amounts) == 10003

    def test_back_loaded_remainder_on_last(self, api):
        """PRD §3.5: "Under `BACK_LOADED`, the latest installments absorb the
        leftover: each of the last *remainder* installments (those whose
        `sequence_no` exceeds the count minus the remainder) carries one cent above
        the base, and the rest carry the base."

        Design: Corner/calculations/installment_back_loaded_remainder_on_last
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=3, frequency="MONTHLY",
                               schedule_basis="BACK_LOADED")
        amounts = [i["amount_cents"] for i in get_installments_sorted(pledge["id"])]
        assert amounts == [3333, 3333, 3334], f"BACK_LOADED 10000/3 -> [3333,3333,3334], got {amounts}"
        assert sum(amounts) == 10000


# ---------------------------------------------------------------------------
# Difficulty Rule 6 — boundary precision: giving-tier MAJOR floor
# ---------------------------------------------------------------------------
class TestGivingTierBoundary:
    def test_major_floor_exactly_one_million(self, api):
        """PRD §3.4: "When it reaches or exceeds 1,000,000 cents (ten thousand
        dollars or more), `giving_status` is `MAJOR`." PRD §3.4: "a lifetime of
        exactly 1,000,000 cents is `MAJOR`."

        Design: Difficulty/boundary_precision_check/giving_tier_major_floor_exactly_one_million
        """
        camp, donor = setup_open_campaign_with_donor(goal_cents=5000000)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=1000000)
        data = validate_success(api.get_donor(donor["id"], GA))
        assert data["lifetime_hard_credit_cents"] == 1000000
        assert data["giving_status"] == "MAJOR", "exactly 1,000,000 cents is MAJOR (inclusive floor)"

    def test_major_floor_minus_one_is_mid(self, api):
        """PRD §3.4: "When it is at least 50,000 cents but strictly below 1,000,000
        cents (from five hundred dollars up to, but not reaching, ten thousand
        dollars), `giving_status` is `MID`."

        999999 cents is one below the MAJOR floor -> MID.

        Design: Difficulty/boundary_precision_check/giving_tier_major_floor_exactly_one_million
        """
        camp, donor = setup_open_campaign_with_donor(goal_cents=5000000)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=999999)
        data = validate_success(api.get_donor(donor["id"], GA))
        assert data["lifetime_hard_credit_cents"] == 999999
        assert data["giving_status"] == "MID", "999999 cents is strictly below the MAJOR floor -> MID"

    def test_entry_ceiling_exactly_fifty_thousand_is_mid(self, api):
        """PRD §3.4: "a lifetime of exactly 50,000 cents is `MID`, and a lifetime of
        exactly 1,000,000 cents is `MAJOR`."

        Design: Difficulty/boundary_precision_check/giving_tier_major_floor_exactly_one_million
        """
        camp, donor = setup_open_campaign_with_donor(goal_cents=5000000)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=50000)
        data = validate_success(api.get_donor(donor["id"], GA))
        assert data["lifetime_hard_credit_cents"] == 50000
        assert data["giving_status"] == "MID", "exactly 50,000 cents is MID (inclusive ENTRY ceiling)"

    def test_below_entry_ceiling_is_entry(self, api):
        """PRD §3.4: "When it is greater than zero but strictly below 50,000 cents
        (that is, under five hundred dollars), `giving_status` is `ENTRY`."

        Design: Difficulty/boundary_precision_check/giving_tier_major_floor_exactly_one_million
        """
        camp, donor = setup_open_campaign_with_donor(goal_cents=5000000)
        create_acknowledged_gift(camp["id"], donor["id"], amount_cents=49999)
        data = validate_success(api.get_donor(donor["id"], GA))
        assert data["giving_status"] == "ENTRY", "49999 cents is strictly below 50000 -> ENTRY"


# ---------------------------------------------------------------------------
# Difficulty Rule 6 — boundary precision: zero-deductible receipt edge
# ---------------------------------------------------------------------------
class TestZeroDeductibleBoundary:
    def test_receipt_zero_deductible_rejected(self, api):
        """PRD §3.3: "A gift bought entirely as a quid-pro-quo benefit thus pins a
        zero deductible." PRD §3.9: "a zero-deductible gift cannot be tax-receipted
        and the attempt is rejected with `ERR_ZERO_DEDUCTIBLE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/receipt_zero_deductible_empty_boundary
        """
        camp, donor = setup_open_campaign_with_donor()
        acked, gift_id = create_acknowledged_gift(
            camp["id"], donor["id"], amount_cents=15000, benefit_value_cents=15000
        )
        assert acked["deductible_amount_cents"] == 0, "benefit == amount pins deductible 0"
        validate_error(api.receipt_gift(gift_id, DR), ApiErrorId.ERR_ZERO_DEDUCTIBLE.value)

    def test_receipt_positive_deductible_succeeds(self, api):
        """PRD §3.9: "It is permitted only while the gift is `ACKNOWLEDGED` and only
        when the gift's `deductible_amount_cents` is at least 1".

        A deductible of exactly 1 (one above the zero boundary) is receiptable.

        Design: Difficulty/boundary_precision_check/receipt_zero_deductible_empty_boundary
        """
        camp, donor = setup_open_campaign_with_donor()
        acked, gift_id = create_acknowledged_gift(
            camp["id"], donor["id"], amount_cents=15000, benefit_value_cents=14999
        )
        assert acked["deductible_amount_cents"] == 1
        data = validate_success(api.receipt_gift(gift_id, DR))
        assert data["status"] == "RECEIPTED"


# ---------------------------------------------------------------------------
# Corner — calculations section
# ---------------------------------------------------------------------------
class TestCornerCalculations:
    def test_soft_credit_split_even_remainder_distribution(self, api):
        """PRD §3.2: "order the other members by `created_at` ascending, give each the
        integer quotient of the gift amount divided by the number of other members,
        then hand the leftover cents ... out one cent each to the earliest members in
        that `created_at` ascending order until the leftover is exhausted; here the
        household total grows by exactly the gift amount, since cents are conserved
        across beneficiaries."

        Design: Corner/calculations/soft_credit_split_even_remainder_distribution
        """
        hh, donors = setup_household_with_members(policy="SPLIT_EVEN", member_count=4)
        giver = donors[0]  # B,C,D are the three others in created_at ASC order
        camp = create_open_campaign(goal_cents=1000000)
        _, gift_id = create_acknowledged_gift(camp["id"], giver["id"], amount_cents=10000)

        rows, _ = _list(api.list_household_soft_credits(hh["id"], CM, params={"limit": 100}))
        by_ben = {r["beneficiary_donor_id"]: r["soft_credit_cents"] for r in rows}
        ordered = [by_ben[donors[i]["id"]] for i in (1, 2, 3)]
        assert ordered == [3334, 3333, 3333], \
            f"SPLIT_EVEN 10000/3 in created_at ASC -> [3334,3333,3333], got {ordered}"
        hh_data = validate_success(api.get_household(hh["id"], CM))
        assert hh_data["total_soft_credit_cents"] == 10000, "cents conserved: total == gift amount"

    def test_match_annual_cap_binding_second_claim(self, api):
        """PRD §3.6: "The remaining cap is the larger of zero and the employer's
        `annual_match_cap_cents` minus that consumed amount. The claim's final
        `matched_amount_cents` is the smaller of its `requested_amount_cents` and that
        remaining cap." PRD §3.6: "when earlier paid claims have consumed enough of the
        cap that the remaining is below the requested amount, the matched amount equals
        the remaining cap".

        Design: Corner/calculations/match_annual_cap_binding_second_claim
        """
        camp = create_open_campaign(goal_cents=5000000)
        emp = create_employer(match_ratio=1.0, min_gift_cents=2500,
                              max_match_cents=1000000, annual_match_cap_cents=60000)
        donor = create_donor(employer_id=emp["id"])
        _, g1 = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=50000)
        c1 = open_match_claim(g1)
        approve_match_claim(c1["id"])
        pay_match_claim(c1["id"])  # consumes 50000 of the 60000 cap
        _, g2 = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        c2 = open_match_claim(g2)
        approve_match_claim(c2["id"])

        data = validate_success(api.pay_match_claim(c2["id"], GA))
        assert data["requested_amount_cents"] == 100000, "per-gift request is floor(100000*1.0)"
        assert data["matched_amount_cents"] == 10000, \
            "only 10000 of the annual cap remains after the prior 50000 paid claim"

    def test_match_ineligible_below_min_gift(self, api):
        """PRD §3.6: "if the donor lacks an employer, or if the gift's `amount_cents`
        is below that employer's `min_gift_cents`, the claim is rejected with
        `ERR_GIFT_INELIGIBLE_FOR_MATCH` (HTTP 422)."

        Design: Corner/calculations/match_ineligible_below_min_gift
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(min_gift_cents=2500)
        donor = create_donor(employer_id=emp["id"])
        _, gift_id = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=1000)
        validate_error(
            api.create_match_claim({"gift_id": gift_id}, GA),
            ApiErrorId.ERR_GIFT_INELIGIBLE_FOR_MATCH.value,
        )

    def test_receipt_numbering_sequential(self, api):
        """PRD §3.9: "The number assigned is one greater than the count of all prior
        `RECEIPT` acknowledgements, formatted as the prefix `RCPT-` followed by that
        running count zero-padded to a width of six digits — so the first receipt is
        `RCPT-000001`, the second `RCPT-000002`, and so on."

        Design: Corner/calculations/receipt_numbering_sequential
        """
        camp = create_open_campaign(goal_cents=1000000)
        d1 = create_donor()
        d2 = create_donor()
        _, g1 = create_acknowledged_gift(camp["id"], d1["id"], amount_cents=5000)
        _, g2 = create_acknowledged_gift(camp["id"], d2["id"], amount_cents=6000)
        validate_success(api.receipt_gift(g1, DR))
        validate_success(api.receipt_gift(g2, DR))

        acks1, _ = _list(api.list_gift_acknowledgements(g1, DR, params={"limit": 100}))
        acks2, _ = _list(api.list_gift_acknowledgements(g2, DR, params={"limit": 100}))
        r1 = [a for a in acks1 if a["kind"] == "RECEIPT"][0]
        r2 = [a for a in acks2 if a["kind"] == "RECEIPT"][0]
        assert r1["receipt_number"] == receipt_number(1), f"first receipt RCPT-000001, got {r1['receipt_number']}"
        assert r2["receipt_number"] == receipt_number(2), f"second receipt RCPT-000002, got {r2['receipt_number']}"

    def test_deductible_with_benefit_value(self, api):
        """PRD §3.3: "It is the gift's `amount_cents` reduced by its
        `benefit_value_cents`, floored at zero — that is, the larger of zero and the
        difference between the two."

        Design: Corner/calculations/deductible_with_benefit_value
        """
        camp, donor = setup_open_campaign_with_donor()
        acked, gift_id = create_acknowledged_gift(
            camp["id"], donor["id"], amount_cents=20000, benefit_value_cents=5000
        )
        assert acked["deductible_amount_cents"] == 15000
        data = validate_success(api.get_gift(gift_id, GA))
        assert data["deductible_amount_cents"] == 15000, "20000 - 5000 == 15000 pinned at acknowledgement"


# ---------------------------------------------------------------------------
# local list helper
# ---------------------------------------------------------------------------
def _list(resp):
    data = get_success_data(resp)
    return rows_of(data), None
