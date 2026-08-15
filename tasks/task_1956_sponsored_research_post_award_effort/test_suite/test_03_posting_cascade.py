"""The four-link expenditure posting cascade (PRD §3.2)."""
from test_helpers import (
    validate_success, api_client, TEST_USERS,
    make_sponsor, make_person, create_active_award, make_commitment,
    post_salary_expenditure, make_cycle, open_cycle, find_award_statement,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]


def _setup_cascade(api, award_number="K2-001"):
    """ACTIVE LOC award (SAL 1000000 + FRINGE 300000, obligated 1950000,
    fringe 3000 bps); PA (IBS 24000000/12) committed 50% key; cycle 2026-H1
    opened BEFORE the salary posting (statement exists, charged 0.0)."""
    sponsor = make_sponsor()
    pa = make_person(ibs=24_000_000, appointment_months=12, full_name="P. Alpha")
    award, lines = create_active_award(
        sponsor["id"], pa["id"], award_number,
        [
            {"category": "PERSONNEL_SALARIES", "authorized_cents": 1_000_000},
            {"category": "FRINGE_BENEFITS", "authorized_cents": 300_000},
        ],
        1_950_000)
    make_commitment(award["id"], pa["id"], 50.0, True)
    cycle = open_cycle(make_cycle()["id"])
    statement = find_award_statement(cycle["id"], award["id"])
    return pa, award, lines["PERSONNEL_SALARIES"], lines["FRINGE_BENEFITS"], cycle, statement


class TestExpenditurePostDepth4LedgerCascade:
    def test_links_1_and_2_line_debits_and_award_aggregates(self, api):
        """PRD §3.2: "Link one stamps `posted_at` with the logical clock
        and debits the ledger: a non-cost-share expenditure adds `amount_cents`
        to its budget line's `spent_cents`, and a salary expenditure
        additionally computes `fringe_cents` as `amount_cents` times the
        award's provisional `fringe_rate_bps` over ten thousand, rounded
        half-up per line, and adds that to the `FRINGE_BENEFITS` line's
        `spent_cents` (when `fringe_cents` is zero this debit is a no-op and no
        `FRINGE_BENEFITS` line need exist)."
        PRD §3.2: "Link two recomputes the award's aggregates:
        `mtdc_spent_cents` becomes the sum of `mtdc_eligible_cents` over the
        award's `POSTED`, non-cost-share expenditures (excluding
        `TRANSFERRED_OUT` sources, including transfer-in mirrors),
        `total_direct_spent_cents` becomes the sum of `amount_cents` over the
        same set, and `f_and_a_accrued_cents` becomes the award's
        `f_and_a_rate_bps` over ten thousand times `mtdc_spent_cents`, rounded
        half-up."

        Design: Difficulty/transitive_cascade/expenditure_post_depth4_ledger_cascade
        """
        pa, award, sal, fr, cycle, statement = _setup_cascade(api)
        assert statement["charged_effort_pct"] == 0.0
        # billable monthly = min(2000000, round(20000000/12)=1666667) = 1666667
        post_salary_expenditure(award["id"], sal["id"], pa["id"],
                                25.0, 1, "2026-03-01T00:00:00Z")
        sal_line = validate_success(api.get_budget_line(sal["id"], GA), 200)
        fr_line = validate_success(api.get_budget_line(fr["id"], GA), 200)
        assert sal_line["spent_cents"] == 416_667   # round(1666667 * 0.25 * 1)
        assert fr_line["spent_cents"] == 125_000    # round(416667 * 0.30)
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["mtdc_spent_cents"] == 416_667
        assert award_after["f_and_a_accrued_cents"] == 208_334  # round(0.5*416667)

    def test_links_3_and_4_draw_pool_and_effort_statement(self, api):
        """PRD §3.2: "Link three recomputes `available_draw_pool_cents` on
        letter-of-credit awards per the pool rule of §3.6. Link four applies
        only to salary: every `EffortStatement` for the (person, award) pair
        whose cycle window covers the `transaction_date` and whose cycle is not
        `CLOSED` recomputes its `charged_effort_pct`."
        PRD §3.6: "Its eligible pool is the sum of `amount_cents` over the
        award's `POSTED`, non-cost-share expenditures with `cash_disbursed`
        true, plus the F&A share computed as the award's `f_and_a_rate_bps`
        over ten thousand times the sum of `mtdc_eligible_cents` over that same
        cash-disbursed set, rounded half-up."

        Design: Difficulty/transitive_cascade/expenditure_post_depth4_ledger_cascade
        """
        pa, award, sal, fr, cycle, statement = _setup_cascade(api)
        post_salary_expenditure(award["id"], sal["id"], pa["id"],
                                25.0, 1, "2026-03-01T00:00:00Z")
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        # pool = 416667 + round(0.5 * 416667) = 416667 + 208334 = 625001
        assert award_after["available_draw_pool_cents"] == 625_001
        st_after = validate_success(api.get_effort_statement(statement["id"], GA), 200)
        # charged = 100 * 416667 / (2000000 * 6) = 3.4722 -> 3.47
        assert st_after["charged_effort_pct"] == 3.47
        assert st_after["version"] == statement["version"] + 1
