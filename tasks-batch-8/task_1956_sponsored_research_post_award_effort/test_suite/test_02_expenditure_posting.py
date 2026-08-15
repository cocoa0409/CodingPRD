"""Expenditure creation, salary charge computation, and the posting cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_expenditure_payload, create_salary_expenditure_payload,
    make_person, setup_sponsor_pi, create_active_award, post_expenditure,
    post_salary_expenditure, make_commitment, setup_salary_award,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]


class TestSalaryCapMinProrationBranches:
    """Difficulty instance: capped vs uncapped branches of the salary charge."""

    def _setup(self, api):
        sponsor, pi = setup_sponsor_pi()
        pa = make_person(ibs=24_000_000, appointment_months=12,
                         full_name="P. Alpha")
        pb = make_person(role_type="RESEARCH_STAFF", ibs=13_500_000,
                         appointment_months=9, full_name="P. Beta")
        award, lines = create_active_award(
            sponsor["id"], pa["id"], "G-001",
            [
                {"category": "PERSONNEL_SALARIES", "authorized_cents": 3_000_000},
                {"category": "FRINGE_BENEFITS", "authorized_cents": 900_000},
            ],
            5_850_000)
        make_commitment(award["id"], pa["id"], 50.0, True)
        make_commitment(award["id"], pb["id"], 25.0, False)
        return sponsor, pa, pb, award, lines["PERSONNEL_SALARIES"]

    def test_capped_branch_computes_amount_over_cap_and_fringe(self, api):
        """PRD §3.2: "When the award carries a salary cap, the cap monthly
        rate is the award's `salary_cap_annual_cents` divided by 12 — the cap
        is always a 12-month-equivalent rate — rounded half-up, and the
        billable monthly rate is the lesser of the two monthly rates; when
        there is no cap, or the IBS monthly rate does not exceed the cap
        monthly rate, the full IBS monthly rate is billable."
        PRD §3.2: "The excess `over_cap_cents` — the IBS-monthly-minus-billable-
        monthly difference multiplied by the same effort fraction and months,
        rounded half-up — is zero whenever the award is uncapped, and when
        nonzero it represents institutional cost share that can never be
        charged to this award."

        Design: Difficulty/combinatorial_formula/salary_cap_min_proration_branches
        """
        _, pa, _, award, sal = self._setup(api)
        # ibs_monthly = 24000000/12 = 2000000; cap_monthly = round(20000000/12)
        # = 1666667; billable = 1666667.
        ea = post_salary_expenditure(award["id"], sal["id"], pa["id"],
                                     50.0, 1, "2026-02-15T00:00:00Z")
        assert ea["amount_cents"] == 833_334      # round(1666667 * 0.50 * 1)
        assert ea["over_cap_cents"] == 166_667    # round(333333 * 0.50 * 1)
        assert ea["fringe_cents"] == 250_000      # round(833334 * 0.30)

    def test_uncapped_branch_bills_full_ibs_and_over_cap_lands_in_cost_share(self, api):
        """PRD §3.2: "when there is no cap, or the IBS monthly rate does not
        exceed the cap monthly rate, the full IBS monthly rate is billable."
        PRD §3.2: "separately, a salary posting's `over_cap_cents` always adds
        to `cost_share_met_cents`, regardless of the `is_cost_share` flag."

        Design: Difficulty/combinatorial_formula/salary_cap_min_proration_branches
        """
        _, pa, pb, award, sal = self._setup(api)
        post_salary_expenditure(award["id"], sal["id"], pa["id"],
                                50.0, 1, "2026-02-15T00:00:00Z")
        # PB: ibs_monthly = 13500000/9 = 1500000 <= cap 1666667 -> uncapped.
        eb = post_salary_expenditure(award["id"], sal["id"], pb["id"],
                                     25.0, 2, "2026-02-15T00:00:00Z")
        assert eb["amount_cents"] == 750_000      # round(1500000 * 0.25 * 2)
        assert eb["over_cap_cents"] == 0
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["cost_share_met_cents"] == 166_667


class TestSalaryAmountInputIgnored:
    def test_salary_amount_input_ignored(self, api):
        """PRD §3.2: "For `SALARY` the caller instead supplies `person_id`,
        `effort_pct` (greater than 0 and at most 100, two decimals), and
        `period_months` (greater than 0, at most 12, up to two decimals), and
        the charge is computed; any `amount_cents` input is ignored."

        Design: Corner/entities/expenditure_salary_amount_input_ignored
        """
        sponsor, person, award, sal, _fringe = setup_salary_award(
            "C-002", salary_line=3_000_000, fringe_line=900_000,
            obligated=5_850_000)
        exp = validate_success(api.create_expenditure(
            create_salary_expenditure_payload(
                award["id"], sal["id"], person["id"], effort_pct=50.0,
                period_months=1, amount_cents=999_999,
                transaction_date="2026-02-15T00:00:00Z"), GC), 201)
        assert exp["amount_cents"] == 833_334


class TestFringePerLineRounding:
    """Difficulty instance: per-line rounding then sum."""

    def _setup(self, api, award_number):
        from test_helpers import make_sponsor
        sp = make_sponsor()
        rnd = make_person(role_type="RESEARCH_STAFF", ibs=13_333_332,
                          appointment_months=12, full_name="R. Nd")
        pi = make_person()
        award, lines = create_active_award(
            sp["id"], pi["id"], award_number,
            [
                {"category": "PERSONNEL_SALARIES", "authorized_cents": 500_000},
                {"category": "FRINGE_BENEFITS", "authorized_cents": 150_000},
            ],
            975_000, fringe_rate_bps=2795)
        make_commitment(award["id"], rnd["id"], 40.0, False)
        return rnd, award, lines["PERSONNEL_SALARIES"], lines["FRINGE_BENEFITS"]

    def test_per_line_fringe_values(self, api):
        """PRD §3.2: "a salary expenditure additionally computes
        `fringe_cents` as `amount_cents` times the award's provisional
        `fringe_rate_bps` over ten thousand, rounded half-up per line, and adds
        that to the `FRINGE_BENEFITS` line's `spent_cents` (when `fringe_cents`
        is zero this debit is a no-op and no `FRINGE_BENEFITS` line need
        exist)."

        Design: Difficulty/combinatorial_formula/fringe_per_line_rounding_then_sum
        """
        rnd, award, sal, _fr = self._setup(api, "F2-001")
        # ibs_monthly = round(13333332/12) = 1111111 (uncapped: 1111111 <= 1666667)
        s1 = post_salary_expenditure(award["id"], sal["id"], rnd["id"],
                                     30.0, 1, "2026-02-01T00:00:00Z")
        s2 = post_salary_expenditure(award["id"], sal["id"], rnd["id"],
                                     10.0, 1, "2026-03-01T00:00:00Z")
        assert s1["amount_cents"] == 333_333      # round(1111111 * 0.30 * 1)
        assert s2["amount_cents"] == 111_111      # round(1111111 * 0.10 * 1)
        assert s1["fringe_cents"] == 93_167       # round(333333 * 0.2795)
        assert s2["fringe_cents"] == 31_056       # round(111111 * 0.2795)

    def test_fringe_line_total_is_sum_of_per_line_rounded_values(self, api):
        """PRD §3.2: "The per-line rounding order is pinned — fringe is rounded
        per expenditure line first, and the `FRINGE_BENEFITS` line total is the
        sum of those per-line rounded values; summing salary first and rounding
        once is a different, incorrect algorithm."

        Design: Difficulty/combinatorial_formula/fringe_per_line_rounding_then_sum
        """
        rnd, award, sal, fr = self._setup(api, "F2-001")
        post_salary_expenditure(award["id"], sal["id"], rnd["id"],
                                30.0, 1, "2026-02-01T00:00:00Z")
        post_salary_expenditure(award["id"], sal["id"], rnd["id"],
                                10.0, 1, "2026-03-01T00:00:00Z")
        fr_line = validate_success(api.get_budget_line(fr["id"], GA), 200)
        # 93167 + 31056 = 124223 (per-line); aggregate order would give
        # round(444444 * 0.2795) = 124222.
        assert fr_line["spent_cents"] == 124_223
        assert fr_line["spent_cents"] != 124_222


class TestExpenditureInitialState:
    def test_expenditure_initial_state_pending_review(self, api):
        """PRD §3.2: "the expenditure lands in `PENDING_REVIEW` with
        `fringe_cents` and `over_cap_cents` computed (fringe zero for
        non-salary) and `transferred_from_id`, `disallow_reason`, `posted_at`,
        and `invoiced_receivable_id` all unset."
        PRD §3.2: "a non-cost-share expenditure adds `amount_cents` to its
        budget line's `spent_cents`" (only on post).

        Design: Corner/state_machines/expenditure_initial_state_pending_review
        """
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "SM-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        exp = validate_success(api.create_expenditure(
            create_expenditure_payload(award["id"], lines["TRAVEL"]["id"],
                                       amount_cents=40_000,
                                       cash_disbursed=True), GC), 201)
        assert exp["status"] == "PENDING_REVIEW"
        assert exp["posted_at"] is None
        line = validate_success(api.get_budget_line(lines["TRAVEL"]["id"], GA), 200)
        assert line["spent_cents"] == 0


class TestLineSufficiencyBoundary:
    def _setup(self, api):
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "BL-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=60_000, cash_disbursed=True)
        return award, lines["TRAVEL"]

    def test_post_exceeding_line_authorized_rejected(self, api):
        """PRD §3.2: "for non-salary types the single line's `spent_cents` plus
        `amount_cents` must not exceed its `authorized_cents`." (shortfall
        returns `ERR_BUDGET_LINE_EXCEEDED`)

        Design: Corner/errors/post_exceeding_line_authorized_rejected
        """
        award, travel = self._setup(api)
        e2 = validate_success(api.create_expenditure(
            create_expenditure_payload(award["id"], travel["id"],
                                       amount_cents=50_000,
                                       transaction_date="2026-03-02T00:00:00Z",
                                       cash_disbursed=True), GC), 201)
        res = api.post_expenditure(e2["id"], GA)
        validate_error(res, ApiErrorId.ERR_BUDGET_LINE_EXCEEDED.value)

    def test_post_exactly_filling_line_allowed(self, api):
        """PRD §3.2: "for non-salary types the single line's `spent_cents` plus
        `amount_cents` must not exceed its `authorized_cents`." (equality
        satisfies "must not exceed")

        Design: Corner/errors/post_exceeding_line_authorized_rejected
        """
        award, travel = self._setup(api)
        e3 = validate_success(api.create_expenditure(
            create_expenditure_payload(award["id"], travel["id"],
                                       amount_cents=40_000,
                                       transaction_date="2026-03-03T00:00:00Z",
                                       cash_disbursed=True), GC), 201)
        posted = validate_success(api.post_expenditure(e3["id"], GA), 200)
        assert posted["status"] == "POSTED"


class TestPostGuards:
    def test_salary_post_without_commitment_rejected(self, api):
        """PRD §3.2: "a salary charge requires that the person hold an
        `EffortCommitment` on the award (`ERR_SALARY_NO_COMMITMENT`)."

        Design: Corner/errors/salary_post_without_commitment_rejected
        """
        from test_helpers import make_sponsor
        sp = make_sponsor()
        pa = make_person(ibs=24_000_000, full_name="P. Alpha")
        award, lines = create_active_award(
            sp["id"], pa["id"], "NC-001",
            [
                {"category": "PERSONNEL_SALARIES", "authorized_cents": 1_000_000},
                {"category": "FRINGE_BENEFITS", "authorized_cents": 300_000},
            ],
            1_950_000)
        exp = validate_success(api.create_expenditure(
            create_salary_expenditure_payload(
                award["id"], lines["PERSONNEL_SALARIES"]["id"], pa["id"],
                effort_pct=25.0, period_months=1), GC), 201)
        res = api.post_expenditure(exp["id"], GA)
        validate_error(res, ApiErrorId.ERR_SALARY_NO_COMMITMENT.value)
        exp_after = validate_success(api.get_expenditure(exp["id"], GA), 200)
        assert exp_after["status"] == "PENDING_REVIEW"

    def test_expenditure_category_type_mismatch_rejected(self, api):
        """PRD §3.2: "the expenditure type must match the line's category
        under a fixed mapping: `SALARY` charges a `PERSONNEL_SALARIES` line,
        `TRAVEL` a `TRAVEL` line, `EQUIPMENT` an `EQUIPMENT` line, `SUPPLIES` a
        `MATERIALS_SUPPLIES` line, `PARTICIPANT_SUPPORT` a
        `PARTICIPANT_SUPPORT` line, and `OTHER_DIRECT` an `OTHER_DIRECT` line;
        any mismatch returns `ERR_CATEGORY_TYPE_MISMATCH`."

        Design: Corner/errors/expenditure_category_type_mismatch_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "CM-001",
            [
                {"category": "TRAVEL", "authorized_cents": 50_000},
                {"category": "MATERIALS_SUPPLIES", "authorized_cents": 100_000},
            ],
            225_000)
        res = api.create_expenditure(
            create_expenditure_payload(
                award["id"], lines["MATERIALS_SUPPLIES"]["id"],
                expenditure_type="TRAVEL", amount_cents=10_000), GC)
        validate_error(res, ApiErrorId.ERR_CATEGORY_TYPE_MISMATCH.value)

    def test_budget_line_from_other_award_rejected(self, api):
        """PRD §3.2: "The line named by `budget_line_id` must belong to the
        same award (`ERR_BUDGET_LINE_AWARD_MISMATCH`), and the expenditure type
        must match the line's category under a fixed mapping: `SALARY` charges
        a `PERSONNEL_SALARIES` line, `TRAVEL` a `TRAVEL` line, `EQUIPMENT` an
        `EQUIPMENT` line, `SUPPLIES` a `MATERIALS_SUPPLIES` line,
        `PARTICIPANT_SUPPORT` a `PARTICIPANT_SUPPORT` line, and `OTHER_DIRECT`
        an `OTHER_DIRECT` line; any mismatch returns
        `ERR_CATEGORY_TYPE_MISMATCH`."

        Design: Corner/errors/budget_line_from_other_award_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        awa, _la = create_active_award(
            sponsor["id"], pi["id"], "XA-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        awb, lb = create_active_award(
            sponsor["id"], pi["id"], "XB-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        res = api.create_expenditure(
            create_expenditure_payload(awa["id"], lb["TRAVEL"]["id"],
                                       amount_cents=10_000), GC)
        validate_error(res, ApiErrorId.ERR_BUDGET_LINE_AWARD_MISMATCH.value)

    def test_subaward_payment_type_manual_create_rejected(self, api):
        """PRD §3.2: "The `SUBAWARD_PAYMENT` type is system-managed — created
        only by subaward-invoice approval — and a manual attempt returns
        `ERR_EXPENDITURE_TYPE_SYSTEM_MANAGED`."

        Design: Corner/errors/subaward_payment_type_manual_create_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "TP-001",
            [{"category": "SUBAWARDS", "authorized_cents": 100_000,
              "mtdc_eligible_cents": 0}], 100_000)
        res = api.create_expenditure(
            create_expenditure_payload(
                award["id"], lines["SUBAWARDS"]["id"],
                expenditure_type="SUBAWARD_PAYMENT", amount_cents=5_000), GC)
        validate_error(res, ApiErrorId.ERR_EXPENDITURE_TYPE_SYSTEM_MANAGED.value)


class TestMtdcInputSetFiltering:
    def _setup(self, api):
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "MX-001",
            [
                {"category": "TRAVEL", "authorized_cents": 150_000},
                {"category": "EQUIPMENT", "authorized_cents": 200_000},
            ],
            425_000, cost_share_committed_cents=30_000)
        return award, lines

    def test_mtdc_excludes_equipment_and_cost_share(self, api):
        """PRD §3.2: "An expenditure's own `mtdc_eligible_cents` is zero for
        `EQUIPMENT`, `PARTICIPANT_SUPPORT`, and cost-share entries; the capped
        subaward portion for `SUBAWARD_PAYMENT`; and `amount_cents` otherwise."
        PRD §3.2: "`mtdc_spent_cents` becomes the sum of `mtdc_eligible_cents`
        over the award's `POSTED`, non-cost-share expenditures..."

        Design: Corner/calculations/mtdc_excludes_equipment_and_cost_share
        """
        award, lines = self._setup(api)
        post_expenditure(award["id"], lines["EQUIPMENT"]["id"],
                         expenditure_type="EQUIPMENT", amount_cents=200_000,
                         cash_disbursed=True)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=30_000, is_cost_share=True)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=50_000, cash_disbursed=True,
                         transaction_date="2026-03-02T00:00:00Z")
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["mtdc_spent_cents"] == 50_000
        assert award_after["f_and_a_accrued_cents"] == 25_000   # round(0.5*50000)

    def test_cost_share_bypasses_line_and_lands_on_tracker(self, api):
        """PRD §3.2: "Cost-share postings bypass the lines and instead add
        `amount_cents` to the award's `cost_share_met_cents`..."
        PRD §3.2: "`total_direct_spent_cents` becomes the sum of `amount_cents`
        over the same set" (POSTED, non-cost-share).

        Design: Corner/calculations/mtdc_excludes_equipment_and_cost_share
        """
        award, lines = self._setup(api)
        post_expenditure(award["id"], lines["EQUIPMENT"]["id"],
                         expenditure_type="EQUIPMENT", amount_cents=200_000,
                         cash_disbursed=True)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=30_000, is_cost_share=True)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=50_000, cash_disbursed=True,
                         transaction_date="2026-03-02T00:00:00Z")
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["total_direct_spent_cents"] == 250_000
        assert award_after["cost_share_met_cents"] == 30_000
        travel = validate_success(api.get_budget_line(lines["TRAVEL"]["id"], GA), 200)
        assert travel["spent_cents"] == 50_000


class TestExistencePriority:
    def test_existence_beats_state_and_shape_on_expenditure_create(self, api):
        """PRD §2.7: "When several validation rules could fire on the same
        request, the server evaluates them in a fixed priority order and
        returns only the first failure." The order's fourth tier is "existence
        of path ids and body foreign-key references, validated left-to-right —
        path first, then body fields in declared order — with one 404 error per
        resource type", which includes `ERR_AWARD_NOT_FOUND`.

        Design: Corner/validations/existence_beats_state_and_shape_on_expenditure_create
        """
        res = api.create_expenditure(
            {"award_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
             "budget_line_id": "7b2e1c0b-1f4d-4a91-9c8b-12e7b6a0f1d2",
             "expenditure_type": "TRAVEL", "amount_cents": 1000,
             "transaction_date": "2026-03-01T00:00:00Z",
             "is_allocable": True, "is_reasonable": True, "is_consistent": True},
            GC)
        validate_error(res, ApiErrorId.ERR_AWARD_NOT_FOUND.value)


class TestImmediateVisibility:
    def test_immediate_visibility_of_post_side_effects(self, api):
        """PRD §1/§3.2: "Every mutation is atomically visible with its
        cascades" and link three "recomputes `available_draw_pool_cents` on
        letter-of-credit awards per the pool rule of §3.6."

        Design: Corner/consistency_model/immediate_visibility_of_post_side_effects
        """
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "IM-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        exp = validate_success(api.create_expenditure(
            create_expenditure_payload(award["id"], lines["TRAVEL"]["id"],
                                       amount_cents=40_000,
                                       cash_disbursed=True), GC), 201)
        posted = validate_success(api.post_expenditure(exp["id"], GA), 200)
        assert posted["status"] == "POSTED"
        line = validate_success(api.get_budget_line(lines["TRAVEL"]["id"], GA), 200)
        assert line["spent_cents"] == 40_000
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        # 40000 cash + F&A share round(0.5 * 40000) = 20000.
        assert award_after["available_draw_pool_cents"] == 60_000


class TestStateBeatsFiscalOnExpenditurePost:
    """Difficulty instance: state validation (suspended award) beats the fiscal
    line-sufficiency check when both would fail."""

    def _setup(self, api):
        sponsor, pi = setup_sponsor_pi()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "S2-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        post_expenditure(award["id"], lines["TRAVEL"]["id"],
                         amount_cents=60_000, cash_disbursed=True)
        e2 = validate_success(api.create_expenditure(
            create_expenditure_payload(award["id"], lines["TRAVEL"]["id"],
                                       amount_cents=50_000,
                                       transaction_date="2026-03-02T00:00:00Z",
                                       cash_disbursed=True), GC), 201)
        # Sponsor suspends before e2's review: post now fails the state gate,
        # and the line would also overflow (60000 + 50000 > 100000).
        so = TEST_USERS["sponsor_official_headers"]
        validate_success(api.suspend_award(
            award["id"], {"reason": "sponsor audit hold"}, so), 200)
        return award, e2

    def test_suspended_award_post_returns_state_error(self, api):
        """PRD §2.7: "(6) state-machine transition validity, including the
        per-machine state errors such as `ERR_AWARD_NOT_ACTIVE` and
        `ERR_CLOSEOUT_INCOMPLETE`" precedes "(12) fiscal ceilings and floors
        (line sufficiency, activation exact-allocation, drawdown pool, subaward
        cumulative ceiling, receivable overpayment, unliquidated obligations,
        MTDC-eligible cap, no-uninvoiced-costs)".
        PRD §3.1: "a `SponsorOfficial` may suspend an `ACTIVE` award (recording
        an optional `reason`), moving it to `SUSPENDED` and blocking all
        financial writes — expenditure create and post, drawdown create and
        submit, transfer approve, invoice approve, and modification submit —
        by state validation; reinstatement returns it to `ACTIVE` with a
        posture recompute, and reinstating an award that is not `SUSPENDED`
        fails with `ERR_AWARD_NOT_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_expenditure_post
        """
        award, e2 = self._setup(api)
        res = api.post_expenditure(e2["id"], GA)
        validate_error(res, ApiErrorId.ERR_AWARD_NOT_ACTIVE.value)

    def test_failed_post_applies_no_side_effects(self, api):
        """PRD §3.2: "Posting is where the ledger moves, and it is a
        `GrantsAccountant` action on a `PENDING_REVIEW` expenditure (any other
        state returns `ERR_EXPENDITURE_NOT_REVIEWABLE`)." A post rejected by
        the state gate fires no side effects, leaving the expenditure pending
        and the line untouched.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_expenditure_post
        """
        award, e2 = self._setup(api)
        api.post_expenditure(e2["id"], GA)
        e2_after = validate_success(api.get_expenditure(e2["id"], GA), 200)
        assert e2_after["status"] == "PENDING_REVIEW"
        lines = validate_success(api.list_budget_lines(
            GA, params={"award_id": award["id"], "category": "TRAVEL"}), 200)
        assert lines[0]["spent_cents"] == 60_000
