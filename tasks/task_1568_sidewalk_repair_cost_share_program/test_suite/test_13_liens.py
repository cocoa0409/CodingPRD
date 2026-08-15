"""Liens: principal netting, interest accrual, payments, statement vs payoff
variants, satisfaction cascade, and foreclosure timing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_forestry_review_id,
    issue_notice,
    make_batch,
    make_bid,
    make_contractor,
    make_contractor_headers,
    make_defect,
    make_draft_notice,
    make_work_item,
    post_payment,
    set_clock,
    setup_inventory,
    setup_lien,
    setup_recorded_lien,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestStatementVsPayoffVariants:
    def _setup(self):
        """RECORDED lien: actual 500000 -> principal 550000 (admin 50000, no
        city-tree credit), assessed 2026-09-22 (day 0); clock at day 30."""
        bundle = setup_recorded_lien(
            actual_repair_cost_cents=500000, parcel_number="P-200",
            segment_code="S-200-1", owner_name="Bob Birch",
            street_address="2 Oak St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=50)
        set_clock("2026-10-22T00:00:00Z")
        return bundle

    def test_statement_projects_to_current_day(self, api):
        """PRD §3.9: "The statement variant, returned by the standard lien
        read, reports `accrued_interest_cents` as stored plus interest projected
        through the current logical clock day."
        PRD §3.9: "First, the interest due is the `principal_remaining_cents`
        multiplied by `interest_rate_bp`, multiplied by the days elapsed since
        `last_accrual_day`, divided by 3,650,000 — the 365-day year scaled for
        basis points — rounded half-up."

        Design: Difficulty/dual_variant_calc/lien_statement_vs_payoff_quote_divergence
        """
        bundle = self._setup()
        lien = bundle["lien"]
        assert lien["owner_principal_cents"] == 550000, \
            "500000 + admin 50000, no city-tree credit"

        stmt = validate_success(api.get_lien_case(lien["id"], FINANCE))
        # round_half_up(550000 * 800 * 30 / 3650000) = round_half_up(3616.43..)
        assert stmt["accrued_interest_cents"] == 3616, \
            "statement variant projects through day 30"

    def test_payoff_projects_fifteen_days_further(self, api):
        """PRD §3.9: "The payoff-quote variant projects further: its response
        carries `principal_remaining_cents`, `accrued_interest_cents`, a
        `projected_interest_cents` computed through the current clock day plus
        15 days, the resulting `good_through_date`, and their total as
        `payoff_total_cents` — so whenever principal remains, the payoff quote
        exceeds the same-day statement balance."

        Design: Difficulty/dual_variant_calc/lien_statement_vs_payoff_quote_divergence
        """
        bundle = self._setup()
        quote = validate_success(api.get_payoff_quote(bundle["lien"]["id"],
                                                      FINANCE))
        # round_half_up(550000 * 800 * 45 / 3650000) = round_half_up(5424.65..)
        assert quote["projected_interest_cents"] == 5425, \
            "payoff variant projects through day 45"
        assert quote["projected_interest_cents"] != 3616
        assert quote["payoff_total_cents"] == 555425
        assert quote["good_through_date"] == "2026-11-06"


class TestWaterfallPaymentRounding:
    def test_first_payment_rounds_interest_at_event(self, api):
        """PRD §3.9: "Third, the payment applies interest-first: it
        extinguishes the accrued interest balance, and only any remainder
        reduces `principal_remaining_cents`."
        PRD §3.9: "Per-event rounding and interest-first application are the
        pinned behavior; a single end-to-end computation or principal-first
        application yields different cents and is non-conformant."

        Design: Difficulty/combinatorial_formula/lien_waterfall_payment_rounding_order
        """
        bundle = setup_recorded_lien(
            actual_repair_cost_cents=500000, parcel_number="P-400",
            segment_code="S-400-1", owner_name="Dan Dogwood",
            street_address="4 Pine St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=50)
        set_clock("2026-10-12T00:00:00Z")  # day 20
        lien = validate_success(post_payment(
            bundle["lien"]["id"], bundle["owner"]["id"], 100000))
        # interest round_half_up(550000*800*20/3650000) = 2411 covered first;
        # 97589 reduces principal
        assert lien["principal_remaining_cents"] == 452411
        assert lien["accrued_interest_cents"] == 0
        assert lien["status"] == "PARTIALLY_PAID"

    def test_second_payment_accrues_on_reduced_principal(self, api):
        """PRD §3.9: "First, the interest due is the `principal_remaining_cents`
        multiplied by `interest_rate_bp`, multiplied by the days elapsed since
        `last_accrual_day`, divided by 3,650,000 — the 365-day year scaled for
        basis points — rounded half-up. Second, that interest is added to
        `accrued_interest_cents` and `last_accrual_day` advances to the payment
        day."

        Design: Difficulty/combinatorial_formula/lien_waterfall_payment_rounding_order
        """
        bundle = setup_recorded_lien(
            actual_repair_cost_cents=500000, parcel_number="P-400",
            segment_code="S-400-1", owner_name="Dan Dogwood",
            street_address="4 Pine St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=50)
        set_clock("2026-10-12T00:00:00Z")  # day 20
        validate_success(post_payment(
            bundle["lien"]["id"], bundle["owner"]["id"], 100000))

        set_clock("2026-11-11T00:00:00Z")  # day 50
        lien = validate_success(post_payment(
            bundle["lien"]["id"], bundle["owner"]["id"], 200000))
        # interest on the REDUCED principal:
        # round_half_up(452411*800*30/3650000) = 2975; 197025 to principal
        assert lien["principal_remaining_cents"] == 255386
        assert lien["outstanding_balance_cents"] == 255386


class TestLienPrincipalNetting:
    def test_city_tree_credit_and_admin_floor(self, api):
        """PRD §3.9: "The administrative fee, `admin_fee_cents`, is the greater
        of 15,000 cents (150 dollars) and ten percent of the actual repair cost
        rounded half-up."
        PRD §3.9: "The credit, `city_credit_cents`, multiplies the actual repair
        cost by the city-caused area first, then divides by the total scope
        area, then rounds half-up — multiply, divide, round, in that order."
        PRD §3.9: "the new lien copies `parcel_id` from its notice, starts in
        `ASSESSED` status, stamps `assessed_at` from the logical clock as day
        zero for accrual, and flips the notice from `CITY_REPAIR_COMPLETED` to
        `LIENED`."

        Design: Corner/calculations/lien_principal_net_city_tree_credit
        """
        bundle = setup_inventory(
            parcel_number="P-C5", segment_code="S-C5-1", owner_name="Tod Tupelo",
            street_address="70 Tupelo St", defect_type="TREE_ROOT_UPHEAVAL",
            measured_offset_inches=0.75, area_sqft=30, city_tree_involved=True)
        review_id = get_forestry_review_id(bundle["defect"]["id"])
        defect2 = make_defect(bundle["segment"]["id"], "SPALLING", 50)
        notice = issue_notice(make_draft_notice(
            bundle["parcel"]["id"],
            [bundle["defect"]["id"], defect2["id"]])["id"])

        set_clock("2026-09-16T00:00:00Z")
        validate_success(api_client.run_delinquency_sweep(COORD))
        validate_success(api.decide_forestry_review(
            review_id, {"decision": "PRUNE_APPROVED"}, TEST_USERS["forestry_headers"]))
        set_clock("2026-09-20T00:00:00Z")
        cleared = validate_success(api.clear_forestry_review(
            review_id, TEST_USERS["forestry_headers"]))
        assert cleared["work_completed_at"] == "2026-09-20T00:00:00Z"

        # Batch window starts exactly 7 days after the clearing (cure buffer).
        batch = make_batch("NB-C5", "2026-09-27", "2026-10-11",
                           "2026-09-24T00:00:00Z")
        item = make_work_item(batch["id"], notice["id"], 80, 1300)
        sealed = validate_success(api_client.seal_bid_batch(batch["id"], COORD))
        contractor = make_contractor("Acme Paving", "L-301", "2026-12-31")
        make_bid(batch["id"], contractor["id"], sealed["version"], 1100)
        set_clock("2026-09-25T00:00:00Z")
        validate_success(api_client.award_bid_batch(batch["id"], COORD))
        set_clock("2026-09-27T00:00:00Z")
        validate_success(api_client.start_batch_work(batch["id"], COORD))
        validate_success(api_client.complete_work_item(
            item["id"], make_contractor_headers(contractor["id"])))
        validate_success(api_client.verify_work_item(
            item["id"], TEST_USERS["inspector2_headers"]))

        lien = validate_success(api.create_lien_case(
            {"notice_id": notice["id"], "actual_repair_cost_cents": 100000},
            FINANCE), 201)
        assert lien["admin_fee_cents"] == 15000, \
            "max(15000, round_half_up(100000 * 10 / 100) = 10000): floor clamps"
        assert lien["city_credit_cents"] == 37500, \
            "round_half_up(100000 * 30 / 80), multiply-then-divide"
        assert lien["owner_principal_cents"] == 77500, \
            "100000 - 37500 + 15000"
        assert lien["status"] == "ASSESSED"
        assert lien["interest_rate_bp"] == 800

        notice_after = validate_success(api.get_repair_notice(notice["id"],
                                                              COORD))
        assert notice_after["status"] == "LIENED"


class TestLienLifecycle:
    def test_payment_before_record_rejected(self, api):
        """PRD §3.9: "Recording — `ASSESSED → RECORDED` by a finance officer —
        makes the lien payable; other transitions out of their source states
        fail with `ERR_INVALID_LIEN_STATE`."

        Design: Corner/state_machines/lien_payment_before_record_rejected
        """
        bundle = setup_lien(actual_repair_cost_cents=500000,
                            parcel_number="P-S6", segment_code="S-S6-1",
                            owner_name="Eli Elder", street_address="56 Elder St",
                            defect_type="VERTICAL_SEPARATION",
                            measured_offset_inches=0.75, area_sqft=50)
        assert bundle["lien"]["status"] == "ASSESSED"

        resp = post_payment(bundle["lien"]["id"], bundle["owner"]["id"], 1000)
        validate_error(resp, ApiErrorId.ERR_INVALID_LIEN_STATE)

    def test_satisfaction_closes_notice(self, api):
        """PRD §3.9: "a payment covering the full outstanding amount satisfies
        the lien — `RECORDED` or `PARTIALLY_PAID → SATISFIED` — which cascades
        the notice from `LIENED` to `CLOSED` and recomputes the parcel's
        `delinquency_flag`."

        Design: Corner/state_machines/lien_satisfaction_closes_notice
        """
        bundle = setup_recorded_lien(
            actual_repair_cost_cents=500000, parcel_number="P-S14",
            segment_code="S-S14-1", owner_name="Mel Mulberry",
            street_address="64 Mulberry St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=50)
        assert bundle["lien"]["owner_principal_cents"] == 550000

        lien = validate_success(post_payment(
            bundle["lien"]["id"], bundle["owner"]["id"], 550000))
        assert lien["status"] == "SATISFIED"
        assert lien["outstanding_balance_cents"] == 0
        assert lien["principal_remaining_cents"] == 0, \
            "full coverage at day 0: zero interest accrued"

        notice = validate_success(
            api.get_repair_notice(bundle["notice"]["id"], COORD))
        assert notice["status"] == "CLOSED", "LIENED -> CLOSED cascade"
        parcel = validate_success(api.get_parcel(bundle["parcel"]["id"], COORD))
        assert parcel["delinquency_flag"] is False

    def test_payment_above_outstanding_rejected(self, api):
        """PRD §3.9: "the owning owner posts payments of `amount_cents`, which
        must be greater than zero (else `ERR_INVALID_REQUEST`) and may not
        exceed the outstanding balance including interest accrued through the
        payment date (else `ERR_PAYMENT_EXCEEDS_BALANCE`)."

        Design: Corner/errors/lien_payment_above_outstanding_rejected
        """
        bundle = setup_recorded_lien(
            actual_repair_cost_cents=500000, parcel_number="P-T9",
            segment_code="S-T9-1", owner_name="Xia Ximenia",
            street_address="105 Ximenia St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=50)

        resp = post_payment(bundle["lien"]["id"], bundle["owner"]["id"],
                            550001)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        lien = validate_success(post_payment(
            bundle["lien"]["id"], bundle["owner"]["id"], 100000))
        assert lien["status"] == "PARTIALLY_PAID"
        assert lien["principal_remaining_cents"] == 450000
        assert lien["outstanding_balance_cents"] == 450000, \
            "day-0 interest is 0; the full amount lands on principal"

    def test_foreclosure_timing_boundary(self, api):
        """PRD §3.9: "When recovery stalls, a `FinanceOfficer` refers the lien
        to foreclosure — `RECORDED` or `PARTIALLY_PAID → FORECLOSURE_REFERRED` —
        permitted only once the logical clock has reached at least 90 days after
        `assessed_at` (earlier attempts fail with `ERR_FORECLOSURE_TOO_EARLY`)
        and only while the outstanding balance including accrued interest
        remains positive."

        Design: Corner/errors/foreclosure_referral_timing_boundary
        """
        bundle = setup_recorded_lien(
            actual_repair_cost_cents=500000, parcel_number="P-T5",
            segment_code="S-T5-1", owner_name="Ute Udal",
            street_address="102 Udal St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=50)

        set_clock("2026-12-20T00:00:00Z")  # day 89 after 2026-09-22
        resp = api.refer_foreclosure(bundle["lien"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_FORECLOSURE_TOO_EARLY)

        set_clock("2026-12-21T00:00:00Z")  # exactly day 90
        lien = validate_success(api.refer_foreclosure(bundle["lien"]["id"],
                                                      FINANCE))
        assert lien["status"] == "FORECLOSURE_REFERRED", \
            "the 90-day minimum is inclusive"
