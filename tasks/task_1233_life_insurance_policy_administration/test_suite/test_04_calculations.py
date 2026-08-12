"""Calculation claims: modal premium rounding order, UL cost-of-insurance
basis, reduced paid-up age tiers, and the cash-surrender waterfall."""
from test_helpers import (
    TEST_USERS,
    add_cash,
    add_rider,
    create_funded_policy,
    create_issued_policy,
    create_policy_with_loan,
    get_policy,
    get_success_data,
    list_ledger,
    make_policyholder_headers,
    originate_loan,
    set_clock,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["agent_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _agent():
    return AGENT


def _ph(bundle):
    return make_policyholder_headers(bundle["insured"]["id"])


class TestModalPremiumNestedRounding:
    def test_quarterly_mode_rounds_monthly_rate_first(self, api):
        """PRD §3.3: "This monthly rate is rounded half-up to whole cents **before** any mode
        multiplication. The monthly rate is then multiplied by the mode factor
        — 1.00 for `MONTHLY`, 2.94 for `QUARTERLY`, 5.82 for `SEMI_ANNUAL`,
        and 11.52 for `ANNUAL` — and the product is rounded half-up to whole
        cents to yield `modal_premium_cents`. The rounding order is part of
        the contract: round the monthly rate first, then multiply by the mode
        factor, then round again."

        face 25000000 / 100000 = 250 thousands; x 33 x 1.80 (STANDARD_TOBACCO)
        x 1 / 100 = 148.50 -> round first -> 149; 149 x 2.94 = 438.06 -> 438.
        (Multiply-then-round would give round(148.50 x 2.94) = 437.)

        Design: Difficulty/combinatorial_formula/modal_premium_nested_rounding
        """
        bundle = create_issued_policy(
            premium_mode="QUARTERLY", face_amount_cents=25_000_000,
            date_of_birth="1985-03-15", tobacco_user=True,
            base_rate=33, underwriting_class="STANDARD_TOBACCO")
        assert bundle["policy"]["modal_premium_cents"] == 438, (
            "round monthly rate (149) before multiplying by 2.94")

    def test_annual_mode_rounds_monthly_rate_first(self, api):
        """PRD §3.3: "The rounding order is part of the contract: round the monthly rate first, then
        multiply by the mode factor, then round again. Computing an annual
        premium first and splitting it across modes is expressly rejected,
        because the two orderings differ by real cents."

        Same rate basis as the quarterly case: monthly 149; 149 x 11.52 =
        1716.48 -> 1716. (Multiply-then-round would give
        round(148.50 x 11.52) = 1711.)

        Design: Difficulty/combinatorial_formula/modal_premium_nested_rounding
        """
        bundle = create_issued_policy(
            premium_mode="ANNUAL", face_amount_cents=25_000_000,
            date_of_birth="1985-03-15", tobacco_user=True,
            base_rate=33, underwriting_class="STANDARD_TOBACCO")
        assert bundle["policy"]["modal_premium_cents"] == 1716, (
            "round monthly rate (149) before multiplying by 11.52")


class TestUniversalLifeCoiBasis:
    def _ul_bundle(self, face_amount_cents, cash_to_add=None):
        bundle = create_issued_policy(
            product_type="UNIVERSAL_LIFE", premium_mode="MONTHLY",
            face_amount_cents=face_amount_cents,
            date_of_birth="1996-05-01", base_rate=100,
            coi_rate_table=[{"attained_age": 30,
                             "monthly_rate_per_thousand_cents": 10}])
        if cash_to_add is not None:
            bundle["policy"] = add_cash(bundle, cash_to_add)
        return bundle

    def test_payment_charges_coi_on_pre_credit_cash_value(self, api):
        """PRD §3.5: "By default the charge is computed against the cash value **before** the
        current cycle's premium credit is applied; where a policy is
        configured with the `front_loaded_coi` flag, the basis instead uses
        the cash value after the current cycle's premium credit, which shrinks
        the net amount at risk and therefore the charge."
        PRD §3.5: "The charge itself is the net amount at risk in cents divided by 100000,
        multiplied by the selected entry's `monthly_rate_per_thousand_cents`,
        multiplied by the policy's underwriting-class multiplier (the same
        multiplier table used at issuance in §3.3), divided by 100, and
        rounded half-up to whole cents."

        face 50000000, pre-credit cash ~500 -> net ~49999500 -> charge 50.
        A post-credit basis (cash ~10000500) would charge 40 instead.

        Design: Difficulty/dual_variant_calc/coi_end_of_month_vs_beginning_of_month
        """
        bundle = self._ul_bundle(50_000_000)
        policy_id = bundle["policy"]["id"]
        get_success_data(api.record_premium_payment(policy_id, 10_000_000, _agent()))
        entries = list_ledger(policy_id)
        coi = [e for e in entries if e["entry_type"] == "COI_DEBIT"]
        assert coi, "a premium posting on UNIVERSAL_LIFE triggers the month's COI"
        assert coi[-1]["amount_cents"] == -50, (
            "default basis uses cash value before this cycle's premium credit; "
            "post-credit basis would yield -40")

    def test_no_charge_when_net_amount_at_risk_not_positive(self, api):
        """PRD §3.5: "The charge is computed on the **net amount at risk**: the policy's
        `face_amount_cents` minus its `cash_value_cents`. When that difference
        is zero or negative, no charge is assessed at all."

        Design: Difficulty/dual_variant_calc/coi_end_of_month_vs_beginning_of_month
        """
        # Fund first so the PRE-credit cash value (the default COI basis,
        # §3.5) already exceeds the face; only then is net at risk <= 0.
        bundle = self._ul_bundle(10_000_000, cash_to_add=20_000_000)
        policy_id = bundle["policy"]["id"]
        before = get_policy(policy_id)["cash_value_cents"]
        assert before >= 10_000_000, "pre-credit cash already covers the face"
        coi_before = len([e for e in list_ledger(policy_id)
                          if e["entry_type"] == "COI_DEBIT"])
        get_success_data(api.record_premium_payment(policy_id, 20_000_000, _agent()))
        after = get_policy(policy_id)["cash_value_cents"]
        coi_after = len([e for e in list_ledger(policy_id)
                         if e["entry_type"] == "COI_DEBIT"])
        assert coi_after == coi_before, "no COI_DEBIT is written when net at risk <= 0"
        assert after == before + 20_000_000, "the full payment credits cash value"


class TestReducedPaidUpAgeTiers:
    def test_attained_age_exactly_40_uses_040_rate(self, api):
        """PRD §3.8: "The conversion rate per dollar of paid-up face is banded by the insured's
        attained age at the election's `effective_date`: 0.30 below age 40,
        0.40 for ages 40 through 49, 0.50 for ages 50 through 59, and 0.65 at
        age 60 and above." And: "The `resulting_face_amount_cents` is the net available value divided by the
        adjusted rate, rounded half-up to whole cents; the policy's
        `face_amount_cents` is updated to that figure, its
        `premium_payment_status` moves to `PAID_UP`, and its `form_status`
        moves from `IN_FORCE` to `REDUCED_PAID_UP`."

        Insured born 1986-05-01; election effective 2026-05-01 -> age exactly
        40 -> rate 0.40; 20002880 / 0.40 = 50007200.

        Design: Difficulty/combinatorial_formula/reduced_paid_up_age_tiered_threshold
        """
        bundle = create_funded_policy(
            20_000_000, premium_mode="ANNUAL", face_amount_cents=50_000_000,
            date_of_birth="1986-05-01")
        resp = api.create_nonforfeiture_election(bundle["policy"]["id"],
                                                 "REDUCED_PAID_UP", _ph(bundle))
        election = validate_success(resp, expected_status=201)
        assert election["surrender_charge_cents"] == 0, "always zero for whole life"
        assert election["net_available_cents"] == election["cash_value_at_election_cents"]
        assert election["resulting_face_amount_cents"] == 50_007_200
        policy = get_policy(bundle["policy"]["id"])
        assert policy["form_status"] == "REDUCED_PAID_UP"
        assert policy["face_amount_cents"] == election["resulting_face_amount_cents"]

    def test_attained_age_39_uses_030_rate(self, api):
        """PRD §3.8: "The conversion rate per dollar of paid-up face is banded by the insured's
        attained age at the election's `effective_date`: 0.30 below age 40,
        0.40 for ages 40 through 49, 0.50 for ages 50 through 59, and 0.65 at
        age 60 and above."
        PRD §2.6: "attained ages are always whole years: the number of days elapsed since the
        insured's `date_of_birth`, divided by 365, rounded down."

        Insured born 1986-05-12; election effective 2026-05-01 -> 14599 days ->
        floor(14599/365) = age 39 -> rate 0.30; 20002880 / 0.30 = 66676266.67
        -> 66676267.

        Design: Difficulty/combinatorial_formula/reduced_paid_up_age_tiered_threshold
        """
        bundle = create_funded_policy(
            20_000_000, premium_mode="ANNUAL", face_amount_cents=50_000_000,
            date_of_birth="1986-05-12")
        resp = api.create_nonforfeiture_election(bundle["policy"]["id"],
                                                 "REDUCED_PAID_UP", _ph(bundle))
        election = validate_success(resp, expected_status=201)
        assert election["resulting_face_amount_cents"] == 66_676_267, (
            "one day younger flips the band from 0.40 to 0.30")


class TestReducedPaidUpCascade:
    def test_election_moves_policy_to_paid_up_and_waives_cycles(self, api):
        """PRD §3.8: "its `premium_payment_status` moves to `PAID_UP`, and its `form_status` moves
        from `IN_FORCE` to `REDUCED_PAID_UP`." And: "Creating any election increments the policy's `version` by one and runs the
        shared cascade: outstanding loans move to `FORECLOSED`, active riders
        move to `TERMINATED`, and future billing cycles are `WAIVED`."

        Design: Difficulty/transitive_cascade/reduced_paid_up_two_hop_cascade
        """
        bundle = create_funded_policy(20_000_000, premium_mode="ANNUAL")
        policy_id = bundle["policy"]["id"]
        version_before = get_policy(policy_id)["version"]

        resp = api.create_nonforfeiture_election(policy_id, "REDUCED_PAID_UP",
                                                 _ph(bundle))
        validate_success(resp, expected_status=201)

        policy = get_policy(policy_id)
        assert policy["form_status"] == "REDUCED_PAID_UP"
        assert policy["premium_payment_status"] == "PAID_UP", (
            "hop-2: the billing dimension follows the form change")
        assert policy["version"] == version_before + 1
        cycles, _m = validate_paginated(api.list_billing_cycles(policy_id, _agent()))
        assert cycles, "at least the first cycle exists"
        assert all(c["status"] in ("PAID", "WAIVED") for c in cycles), (
            "every cycle stands PAID or is WAIVED after the election")

    def test_election_forecloses_loans_and_terminates_riders(self, api):
        """PRD §3.8: "Creating any election increments the policy's `version` by one and runs the
        shared cascade: outstanding loans move to `FORECLOSED`, active riders
        move to `TERMINATED`, and future billing cycles are `WAIVED`."

        Design: Difficulty/transitive_cascade/reduced_paid_up_two_hop_cascade
        """
        bundle, loan = create_policy_with_loan(3_000_000, cash_to_add=20_000_000,
                                               premium_mode="ANNUAL")
        rider = add_rider(bundle, "ACCIDENTAL_DEATH_BENEFIT", 1_000_000)
        policy_id = bundle["policy"]["id"]

        resp = api.create_nonforfeiture_election(policy_id, "REDUCED_PAID_UP",
                                                 _ph(bundle))
        validate_success(resp, expected_status=201)

        assert get_success_data(api.get_loan(policy_id, loan["id"],
                                             _agent()))["status"] == "FORECLOSED"
        assert get_success_data(api.get_rider(rider["id"],
                                              _agent()))["status"] == "TERMINATED"


class TestCashSurrenderWaterfall:
    def test_universal_life_waterfall_net_of_loan_and_charge(self, api):
        """PRD §3.8: "Under `CASH_SURRENDER`, the payout follows a waterfall: start from the gross
        cash value, subtract outstanding loan principal, subtract accrued loan
        interest, subtract the surrender charge, and pay the remainder as
        `payout_cents` — floored at zero should the subtractions overrun." And: "the `outstanding_loan_offset_cents` — outstanding loan principal plus accrued
        interest at the election date". And: "the charge is the cash value multiplied by that bracket's
        `surrender_charge_pct_bps`, divided by 10000, rounded half-up to whole
        cents."

        Design: Corner/calculations/cash_surrender_waterfall_order
        """
        bundle = create_issued_policy(
            product_type="UNIVERSAL_LIFE", premium_mode="ANNUAL",
            face_amount_cents=20_000_000,
            date_of_birth="1980-01-01", base_rate=100,
            coi_rate_table=[{"attained_age": 40,
                             "monthly_rate_per_thousand_cents": 15}],
            surrender_charge_schedule=[{"policy_year_min_inclusive": 1,
                                        "surrender_charge_pct_bps": 1000}])
        bundle["policy"] = add_cash(bundle, 10_000_000)
        policy_id = bundle["policy"]["id"]
        loan = originate_loan(bundle, 3_000_000)
        set_clock("2026-11-01T00:00:00Z")
        accrued = validate_success(api.accrue_interest(policy_id, loan["id"], ADMIN))
        # 184 days at 500 bps on 3000000: round(150000 x 184 / 365) = 75616.
        assert accrued["accrued_interest_cents"] == 75_616
        expected_offset = (accrued["outstanding_principal_cents"]
                           + accrued["accrued_interest_cents"])

        resp = api.create_nonforfeiture_election(policy_id, "CASH_SURRENDER",
                                                 _ph(bundle))
        election = validate_success(resp, expected_status=201)

        cash_at = election["cash_value_at_election_cents"]
        expected_charge = (cash_at * 1000 + 5000) // 10000  # round half-up
        assert election["outstanding_loan_offset_cents"] == expected_offset
        assert election["surrender_charge_cents"] == expected_charge, (
            "policy_year 1 bracket of 1000 bps applies to the cash value")
        assert election["net_available_cents"] == (
            cash_at - expected_offset - expected_charge)
        assert election["payout_cents"] == max(election["net_available_cents"], 0)

        policy = get_policy(policy_id)
        assert policy["form_status"] == "SURRENDERED"
        assert policy["premium_payment_status"] == "PAID_UP"
        assert policy["cash_value_cents"] == 0, "SURRENDER_DEBIT zeroes the cash value"
        assert get_success_data(api.get_loan(policy_id, loan["id"],
                                             _agent()))["status"] == "FORECLOSED"

    def test_whole_life_surrender_pays_full_cash_value(self, api):
        """PRD §3.8: "the `surrender_charge_cents` applied (universal life only; always zero for
        whole life)" and "Under `CASH_SURRENDER`, the payout follows a waterfall: start from the gross
        cash value, subtract outstanding loan principal, subtract accrued loan
        interest, subtract the surrender charge, and pay the remainder as
        `payout_cents`".

        With no loans and no surrender charge, payout equals the cash value.

        Design: Corner/calculations/cash_surrender_waterfall_order
        """
        bundle = create_funded_policy(10_000_000, premium_mode="ANNUAL")
        resp = api.create_nonforfeiture_election(bundle["policy"]["id"],
                                                 "CASH_SURRENDER", _ph(bundle))
        election = validate_success(resp, expected_status=201)
        assert election["surrender_charge_cents"] == 0
        assert election["outstanding_loan_offset_cents"] == 0
        assert election["payout_cents"] == election["cash_value_at_election_cents"]
        policy = get_policy(bundle["policy"]["id"])
        assert policy["form_status"] == "SURRENDERED"
        assert policy["cash_value_cents"] == 0
