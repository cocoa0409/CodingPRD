"""Tax liability accounts, safe-harbor deposit requirement, late penalties."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_account_balance_invariant,
    create_deposit,
    create_employer,
    create_rule_pack,
    get_employer,
    get_tax_accounts_by_type,
    make_payroll_admin_headers,
    setup_active_worker,
    setup_finalized_pay_run,
    validate_error,
    validate_success,
)


def _setup_employer_with_one_finalized_run(guarantee_per_week, prior_year=0,
                                           state_code="AA", legal_name="Fam T"):
    """One FINALIZED weekly pay run on the guarantee basis for a single worker.
    Guarantee 6002 min at 50 cents/min yields gross 300100; the FICA accounts
    accrue 22957 each, FUTA_ER 1801 — federal accrual 47715 per period."""
    create_rule_pack(state_code, sit_rate=0.05)
    employer, worker, _a = setup_active_worker(
        state_code,
        worker_overrides={"ssn": "123456789"},
        agreement_overrides={"guaranteed_minutes_per_week": guarantee_per_week},
        employer_overrides={"legal_name": legal_name,
                            "prior_year_schedule_h_cents": prior_year},
        agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
    )
    run = setup_finalized_pay_run(employer["id"])
    return employer, worker, run


class TestProjectedVsAccruedVariants:
    def test_accrued_is_chronological_sum_after_first_finalize(self, api):
        """PRD §3.9: "`accrued_cents` is the chronological sum of finalized paycheck line amounts for the type and year, with voided paychecks subtracting."
        PRD §3.9: "Accounts are created lazily at pay-run finalize in the fixed order `FICA_EE`, `FICA_ER`, `FUTA_ER`, `SIT_EE`, `SUTA_ER` — all five, even when the line amount for a type is 0."

        Design: Difficulty/dual_variant_calc/schedule_h_projection_vs_ytd_actual
        """
        employer, _w, _r = _setup_employer_with_one_finalized_run(2400)
        accounts = get_tax_accounts_by_type(employer["id"], 2026)
        assert set(accounts.keys()) == {"FICA_EE", "FICA_ER", "FUTA_ER", "SIT_EE", "SUTA_ER"}
        # Guarantee fallback gross 2400 x 50 = 120000, below the FICA threshold.
        assert accounts["FICA_EE"]["accrued_cents"] == 0
        # Quarter wages 120000 >= 100000 -> FUTA applies: round(120000 x 0.006) = 720.
        assert accounts["FUTA_ER"]["accrued_cents"] == 720
        # SUTA chronological variant: round(120000 x 0.02) = 2400.
        assert accounts["SUTA_ER"]["accrued_cents"] == 2400

    def test_projected_annual_extends_per_period_average(self, api):
        """PRD §3.9: "The `projected_annual_cents` field is a forward-looking variant computed as `accrued_cents` plus the per-period average times the number of remaining pay periods in the tax year, where the per-period average is `accrued_cents` divided by the count of the employer's `FINALIZED` pay runs with `pay_date` in the year (floored at 1 to avoid division by zero), and the total periods per year derive from `pay_frequency`: 52 for `WEEKLY`, 26 for `BIWEEKLY`, 24 for `SEMIMONTHLY`, 12 for `MONTHLY`."

        Design: Difficulty/dual_variant_calc/schedule_h_projection_vs_ytd_actual
        """
        employer, _w, _r = _setup_employer_with_one_finalized_run(2400)
        accounts = get_tax_accounts_by_type(employer["id"], 2026)
        suta = accounts["SUTA_ER"]
        # Forward-looking variant: 2400 + (2400 / 1 elapsed) x 51 remaining of 52.
        assert suta["projected_annual_cents"] == 124800
        assert suta["accrued_cents"] == 2400
        assert suta["projected_annual_cents"] != suta["accrued_cents"]


class TestLateDepositPenaltyCascade:
    def test_late_days_and_tiered_penalty_on_required_amount(self, api):
        """PRD §3.9: "`late_days` is the number of whole days by which `remitted_on` exceeds `due_date`, floored at zero."
        PRD §3.9: "The **late-deposit penalty** is tiered over the *required* amount (not the remitted amount): 0 days late, no penalty; 1 through 5 days late, 2% of `required_amount_cents`; 6 through 15 days late, 5%; 16 or more days late, 10%."

        Design: Difficulty/transitive_cascade/late_deposit_penalty_posture_cascade
        """
        employer, _w, _r = _setup_employer_with_one_finalized_run(6002)
        assert get_employer(employer["id"])["compliance_posture"] == "CLEAR"

        # Safe harbor: 47715 x 52 = 2481180 projected; Q1 installment 620295.
        # Due 2026-04-15, remitted 2026-04-25 -> 10 days late -> 5% tier.
        deposit = create_deposit(employer["id"], 2026, 1, 620295, "2026-04-25")
        assert deposit["required_amount_cents"] == 620295
        assert deposit["due_date"] == "2026-04-15"
        assert deposit["late_days"] == 10
        assert deposit["penalty_cents"] == 31015

    def test_penalty_lands_on_fica_er_and_posture_flips_attention(self, api):
        """PRD §3.9: "The full penalty of every late deposit for the year lands on the `FICA_ER` account's `penalty_cents`; every other account's `penalty_cents` is always 0."
        PRD §2.9: "Otherwise, the posture is `ATTENTION` when any `TaxDeposit` of the employer has `late_days` greater than 0, or any `QuarterlyFiling` of the employer is in `REJECTED` status."
        PRD §3.9: "The deposit's `amount_cents` is then allocated across the year's accounts by a waterfall in the fixed order `FICA_EE`, `FICA_ER`, `FUTA_ER`, `SIT_EE`, `SUTA_ER`, each account's `deposited_cents` filled up to its balance; the portion left over after every account reaches zero is recorded as `unapplied_cents`."

        Design: Difficulty/transitive_cascade/late_deposit_penalty_posture_cascade
        """
        employer, _w, _r = _setup_employer_with_one_finalized_run(6002)
        deposit = create_deposit(employer["id"], 2026, 1, 620295, "2026-04-25")
        # Waterfall: 22957 + (22957 + 31015 penalty) + 1801 + 15005 + 6002 = 99737.
        assert deposit["unapplied_cents"] == 520558

        accounts = get_tax_accounts_by_type(employer["id"], 2026)
        fica_er = accounts["FICA_ER"]
        assert fica_er["penalty_cents"] == 31015
        assert fica_er["balance_cents"] == 0
        assert_account_balance_invariant(fica_er)
        assert accounts["FICA_EE"]["penalty_cents"] == 0
        assert accounts["SUTA_ER"]["penalty_cents"] == 0

        assert get_employer(employer["id"])["compliance_posture"] == "ATTENTION"


class TestSafeHarborPriorYearCap:
    def test_prior_year_cap_leg_binds_requirement(self, api):
        """PRD §3.9: "Third, the safe-harbor cap is the smaller of `projected_annual` and 110% of `prior_year_schedule_h_cents` rounded half-up — when `prior_year_schedule_h_cents` is greater than 0; otherwise the cap is `projected_annual`."
        PRD §3.9: "Fifth, the quarterly installment is the annual required divided by 4, rounded half-up to cents."

        Design: Corner/calculations/safe_harbor_prior_year_cap_leg
        """
        employer, _w, _r = _setup_employer_with_one_finalized_run(
            6002, prior_year=100000, legal_name="Fam Cap2"
        )
        # min(2481180, round(1.10 x 100000)) = 110000; installment round(110000/4) = 27500.
        deposit = create_deposit(employer["id"], 2026, 1, 27500, "2026-04-10")
        assert deposit["required_amount_cents"] == 27500
        assert deposit["late_days"] == 0
        assert deposit["penalty_cents"] == 0
        assert deposit["unapplied_cents"] == 0

        accounts = get_tax_accounts_by_type(employer["id"], 2026)
        # Waterfall: FICA_EE filled to 22957 first; the remaining 4543 land on FICA_ER.
        assert accounts["FICA_EE"]["balance_cents"] == 0
        assert accounts["FICA_ER"]["deposited_cents"] == 4543
        assert accounts["FICA_ER"]["balance_cents"] == 18414


class TestDepositGuards:
    def test_deposit_one_cent_below_required_returns_422(self, api):
        """PRD §3.9: "At creation, the system captures `required_amount_cents` from the safe-harbor requirement (below) and rejects the deposit with `ERR_DEPOSIT_BELOW_REQUIRED` (HTTP 422) when `amount_cents` falls short."

        Design: Corner/validations/deposit_below_required_returns_422
        """
        employer, _w, _r = _setup_employer_with_one_finalized_run(6002)
        resp = api.create_deposit(
            employer["id"],
            {"tax_year": 2026, "quarter": 1, "amount_cents": 620294, "remitted_on": "2026-04-10"},
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_BELOW_REQUIRED)

    def test_deposit_remitted_in_the_future_returns_400(self, api):
        """PRD §3.9: "`remitted_on` must not lie after the logical-clock current date (otherwise `ERR_INVALID_REQUEST`)."
        PRD §2.5: "The logical clock's default value, before any client has set it, is exactly **2026-08-01T00:00:00Z** — it never silently falls back to wall-clock time."

        Design: Corner/validations/deposit_with_future_remittance_returns_400
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        resp = api.create_deposit(
            employer["id"],
            {"tax_year": 2026, "quarter": 1, "amount_cents": 0, "remitted_on": "2026-09-01"},
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
