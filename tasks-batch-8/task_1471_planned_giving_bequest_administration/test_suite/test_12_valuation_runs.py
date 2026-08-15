"""Actuarial valuation runs: posting gates, closed-window overlap, the
revaluation cascade, CRAT/CRUT divergence, and provisional-vs-final deduction."""
from test_helpers import (
    BOOKED_AGE70_RATE600_DEDUCTION_CENTS,
    ILL_AGE70_DEDUCTION_CENTS,
    REVAL_CRAT_LIABILITY_CENTS,
    REVAL_CRAT_REMAINDER_CENTS,
    REVAL_CRUT_CORPUS_CENTS,
    REVAL_CRUT_ANNUAL_ANNUITY_CENTS,
    REVAL_CRUT_LIABILITY_CENTS,
    REVAL_CRUT_PAYMENT_CENTS,
    REVAL_CRUT_REMAINDER_CENTS,
    REVAL_CRUT_TOTAL_SCHEDULED_CENTS,
    REVAL_TOTAL_LIABILITY_CENTS,
    REVAL_TOTAL_REMAINDER_CENTS,
    ApiErrorId,
    contribute_reserve,
    list_payments,
    make_active_agreement,
    make_active_rate_table,
    make_compliance_headers,
    make_donor,
    make_draft_agreement,
    make_illustration,
    make_posted_valuation_run,
    make_valuation_run,
    make_verified_designation,
    validate_error,
    validate_success,
)

CO1 = make_compliance_headers("co-1")
CO2 = make_compliance_headers("co-2")


class TestValuationPostGates:
    def test_valuation_post_without_rate_table_rejected(self, api, compliance_headers):
        """PRD §3.9: posting "requires an `ACTIVE` rate table covering
        `valuation_date` to exist (`ERR_NO_ACTIVE_RATE_TABLE`, HTTP 422)".

        Design: Corner/validations/valuation_post_without_rate_table_rejected
        """
        run = make_valuation_run(creator_headers=CO1)
        resp = api.post_valuation_run(run["id"], CO2)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_TABLE)
        assert resp.status_code == 422
        after = validate_success(api.get_valuation_run(run["id"], compliance_headers))
        assert after["status"] == "DRAFT"

    def test_valuation_double_post_rejected(self, api, compliance_headers):
        """PRD §3.9: "Posting the run — by a `ComplianceOfficer` who must
        differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`) —
        requires the run still be `DRAFT` (a re-post is rejected with
        `ERR_VALUATION_ALREADY_POSTED`, HTTP 409)".

        Design: Corner/validations/valuation_double_post_rejected
        """
        make_active_rate_table()
        run = make_posted_valuation_run(creator_headers=CO1, poster_headers=CO2)
        assert run["status"] == "POSTED"

        # The original poster passes the SoD check but hits the state gate.
        resp = api.post_valuation_run(run["id"], CO2)
        validate_error(resp, ApiErrorId.ERR_VALUATION_ALREADY_POSTED)
        assert resp.status_code == 409


class TestClosedWindowOverlap:
    def _setup_posted_first_run(self, api):
        make_active_rate_table()
        return make_posted_valuation_run(
            coverage_start="2026-01-01T00:00:00Z",
            coverage_end="2026-06-30T00:00:00Z",
            valuation_date="2026-03-01T00:00:00Z",
            creator_headers=CO1,
            poster_headers=CO2,
        )

    def test_shared_boundary_date_is_overlap(self, api, compliance_headers):
        """PRD §3.9: posting "requires its closed coverage window not to
        intersect the closed window of any other `POSTED` run — note that
        sharing even a single boundary date **is** an overlap, unlike the
        half-open rate-table windows — (`ERR_VALUATION_WINDOW_OVERLAP`,
        HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/valuation_run_closed_interval_touch_rejected
        """
        first = self._setup_posted_first_run(api)
        assert first["status"] == "POSTED"
        assert first["agreements_revalued_count"] == 0

        # Second run's window touches the first at the single date 2026-06-30.
        touching = make_valuation_run(
            coverage_start="2026-06-30T00:00:00Z",
            coverage_end="2026-12-31T00:00:00Z",
            valuation_date="2026-09-01T00:00:00Z",
            creator_headers=CO1,
        )
        resp = api.post_valuation_run(touching["id"], CO2)
        validate_error(resp, ApiErrorId.ERR_VALUATION_WINDOW_OVERLAP)
        assert resp.status_code == 409

    def test_window_starting_next_day_posts(self, api, compliance_headers):
        """PRD §3.9: "Creating a run supplies a fiscal coverage window —
        `coverage_start` and `coverage_end`, both inclusive, forming a
        **closed** interval" — so a window starting the day after another
        POSTED run's end shares no date and posts cleanly."

        Design: Difficulty/resource_temporal_overlap/valuation_run_closed_interval_touch_rejected
        """
        first = self._setup_posted_first_run(api)
        assert first["status"] == "POSTED"

        disjoint = make_valuation_run(
            coverage_start="2026-07-01T00:00:00Z",
            coverage_end="2026-12-31T00:00:00Z",
            valuation_date="2026-09-01T00:00:00Z",
            creator_headers=CO1,
        )
        posted = validate_success(api.post_valuation_run(disjoint["id"], CO2))
        assert posted["status"] == "POSTED"


class TestRevaluationCascade:
    def _setup_crut_active_with_run(self, api):
        """CRUT (10M, 600bps, QUARTERLY, age 80, funding 2026-08) ACTIVE with
        80 payments @150000 (clock untouched so all stay SCHEDULED); DRAFT run
        covering 2027 with a corpus update to 12000000."""
        donor = make_donor(full_name="Reval Cascade")
        make_active_rate_table()
        agreement, payments = make_active_agreement(
            donor["id"], vehicle_type="CRT_UNITRUST", payout_rate_bps=600
        )
        run = make_valuation_run(
            coverage_start="2027-01-01T00:00:00Z",
            coverage_end="2027-12-31T00:00:00Z",
            valuation_date="2027-08-01T00:00:00Z",
            corpus_updates=[
                {"agreement_id": agreement["id"], "new_corpus_cents": REVAL_CRUT_CORPUS_CENTS}
            ],
            creator_headers=CO1,
        )
        return agreement, payments, run

    def test_post_recomputes_corpus_annuity_and_schedule(self, api, compliance_headers):
        """PRD §3.9: "apply the matching `corpus_updates` entry first when the
        vehicle is `CRT_UNITRUST` (setting `corpus_value_cents` to
        `new_corpus_cents`)".
        PRD §3.9: "for `CRT_UNITRUST`, recompute `annual_annuity_cents` as the
        new corpus multiplied by `payout_rate_bps` and divided by 10000,
        rounded half-up".
        PRD §3.9: "**Hop 2:** for each `CRT_UNITRUST` agreement revalued in
        hop 1, recompute the `amount_cents` of its `SCHEDULED` payments as the
        new annual annuity divided by the frequency divisor, rounded half-up —
        so a corpus update changes all future scheduled payment amounts."
        PRD §3.9: "**Hop 3:** for each such agreement, recompute
        `total_scheduled_cents` as the sum of its payment amounts."

        Design: Difficulty/transitive_cascade/valuation_post_revaluation_cascade
        """
        agreement, _payments, run = self._setup_crut_active_with_run(api)
        validate_success(api.post_valuation_run(run["id"], CO2))

        after = validate_success(api.get_gift_agreement(agreement["id"], compliance_headers))
        assert after["corpus_value_cents"] == REVAL_CRUT_CORPUS_CENTS
        assert after["annual_annuity_cents"] == REVAL_CRUT_ANNUAL_ANNUITY_CENTS
        assert after["total_scheduled_cents"] == REVAL_CRUT_TOTAL_SCHEDULED_CENTS

        scheduled, meta = list_payments(agreement["id"], status="SCHEDULED")
        assert meta["total_count"] == 80
        for payment in scheduled:
            assert payment["amount_cents"] == REVAL_CRUT_PAYMENT_CENTS

    def test_post_updates_liability_remainder_and_run_aggregates(
        self, api, compliance_headers
    ):
        """PRD §3.9: "recompute `actuarial_liability_cents` as the (possibly
        new) annual annuity times the annuity-immediate factor at the new term
        and rate, rounded half-up; recompute `remainder_value_cents` as corpus
        minus liability floored at zero".
        PRD §3.9: "The run records `agreements_revalued_count` (the number of
        agreements processed), `total_liability_cents` and
        `total_remainder_cents` (the sums across revalued agreements)".

        Design: Difficulty/transitive_cascade/valuation_post_revaluation_cascade
        """
        agreement, _payments, run = self._setup_crut_active_with_run(api)
        posted = validate_success(api.post_valuation_run(run["id"], CO2))
        assert posted["agreements_revalued_count"] == 1
        assert posted["total_liability_cents"] == REVAL_CRUT_LIABILITY_CENTS
        assert posted["total_remainder_cents"] == REVAL_CRUT_REMAINDER_CENTS

        after = validate_success(api.get_gift_agreement(agreement["id"], compliance_headers))
        # Age advanced one whole year to 81 (n=19, 5%): liability 8701431.
        assert after["actuarial_liability_cents"] == REVAL_CRUT_LIABILITY_CENTS
        assert after["remainder_value_cents"] == REVAL_CRUT_REMAINDER_CENTS


class TestCratVsCrutDivergence:
    def _setup_both_vehicles_with_run(self, api, estate_manager_headers, gift_admin_headers):
        """CRAT and CRUT with identical economics (10M, 600bps, QUARTERLY,
        age 80, funding 2026-08), both ACTIVE with 80 payments @150000; DRAFT
        run over 2027 with a corpus update for the CRUT only."""
        donor = make_donor(full_name="Dual Variant")
        make_active_rate_table()
        crat, crat_payments = make_active_agreement(
            donor["id"], vehicle_type="CRT_ANNUITY", payout_rate_bps=600
        )
        crut, crut_payments = make_active_agreement(
            donor["id"], vehicle_type="CRT_UNITRUST", payout_rate_bps=600
        )
        run = make_valuation_run(
            coverage_start="2027-01-01T00:00:00Z",
            coverage_end="2027-12-31T00:00:00Z",
            valuation_date="2027-08-01T00:00:00Z",
            corpus_updates=[
                {"agreement_id": crut["id"], "new_corpus_cents": REVAL_CRUT_CORPUS_CENTS}
            ],
            creator_headers=CO1,
        )
        return crat, crut, run

    def test_crat_frozen_while_crut_revalues(self, api, compliance_headers, gift_admin_headers, estate_manager_headers):
        """PRD §3.9: "for `CRT_UNITRUST`, recompute `annual_annuity_cents` as
        the new corpus multiplied by `payout_rate_bps` and divided by 10000,
        rounded half-up — unitrust annuities are annually revalued off current
        corpus, whereas `CGA` and `CRT_ANNUITY` annuities are fixed at funding
        and never change".

        Design: Difficulty/dual_variant_calc/crat_vs_crut_payment_divergence
        """
        crat, crut, run = self._setup_both_vehicles_with_run(
            api, estate_manager_headers, gift_admin_headers
        )
        validate_success(api.post_valuation_run(run["id"], CO2))

        crat_after = validate_success(api.get_gift_agreement(crat["id"], compliance_headers))
        crut_after = validate_success(api.get_gift_agreement(crut["id"], compliance_headers))
        assert crat_after["annual_annuity_cents"] == 600000
        assert crut_after["annual_annuity_cents"] == REVAL_CRUT_ANNUAL_ANNUITY_CENTS

        crat_payments, _ = list_payments(crat["id"], status="SCHEDULED")
        crut_payments, _ = list_payments(crut["id"], status="SCHEDULED")
        for payment in crat_payments:
            assert payment["amount_cents"] == 150000
        for payment in crut_payments:
            assert payment["amount_cents"] == REVAL_CRUT_PAYMENT_CENTS
        # Identical inputs diverge purely by vehicle variant.
        assert crat_payments[0]["amount_cents"] != crut_payments[0]["amount_cents"]

    def test_run_aggregates_sum_both_vehicles(self, api, compliance_headers, gift_admin_headers, estate_manager_headers):
        """PRD §3.9: "The run records `agreements_revalued_count` (the number
        of agreements processed), `total_liability_cents` and
        `total_remainder_cents` (the sums across revalued agreements), stamps
        `posted_at` from the logical clock, stores the poster as
        `posted_by_user_id`, and moves to the terminal `POSTED` status".

        Design: Difficulty/dual_variant_calc/crat_vs_crut_payment_divergence
        """
        crat, crut, run = self._setup_both_vehicles_with_run(
            api, estate_manager_headers, gift_admin_headers
        )
        posted = validate_success(api.post_valuation_run(run["id"], CO2))
        assert posted["status"] == "POSTED"
        assert posted["agreements_revalued_count"] == 2
        # CRAT liability 7251193 + CRUT liability 8701431.
        assert posted["total_liability_cents"] == REVAL_TOTAL_LIABILITY_CENTS
        assert posted["total_remainder_cents"] == REVAL_TOTAL_REMAINDER_CENTS

        crat_after = validate_success(api.get_gift_agreement(crat["id"], compliance_headers))
        assert crat_after["actuarial_liability_cents"] == REVAL_CRAT_LIABILITY_CENTS
        assert crat_after["remainder_value_cents"] == REVAL_CRAT_REMAINDER_CENTS


class TestProvisionalVsBookedDeduction:
    def test_deduction_provisional_vs_booked_divergence(
        self, api, gift_officer_headers, gift_admin_headers
    ):
        """PRD §3.2: "`illustrated_deduction_cents`, the provisional charitable
        deduction computed under the pinned table at illustration time using
        the same actuarial method described for execution in §3.3. These
        figures are purely informational."
        PRD §3.3: "A successful execution pins the agreement's booked
        economics: `annual_annuity_cents` (null for `BEQUEST`);
        `booked_deduction_cents` per the method above".
        PRD §2.7: "Illustrations and directly created gift agreements pin a
        rate table at creation: the system selects the `ACTIVE` table whose
        half-open window covers the supplied `funding_month` and stores it as
        `rate_table_id`."

        Design: Corner/calculations/deduction_provisional_vs_booked_divergence
        """
        donor = make_donor(full_name="Rate Divergence")
        t1 = make_active_rate_table(
            label="T1-5pct",
            discount_rate_bps=500,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-12-01T00:00:00Z",
        )
        t2 = make_active_rate_table(
            label="T2-6pct",
            discount_rate_bps=600,
            effective_from="2026-12-01T00:00:00Z",
            effective_to="2027-06-01T00:00:00Z",
        )

        illustration = make_illustration(
            donor["id"], vehicle_type="CGA", annuitant_1_age=70, funding_month="2026-08"
        )
        assert illustration["rate_table_id"] == t1["id"]
        assert illustration["illustrated_deduction_cents"] == ILL_AGE70_DEDUCTION_CENTS

        agreement = make_draft_agreement(
            donor["id"],
            vehicle_type="CGA",
            payout_rate_bps=600,
            annuitant_1_age=70,
            funding_month="2026-12",
        )
        assert agreement["rate_table_id"] == t2["id"]
        make_verified_designation(agreement["id"])
        # Pre-fund the reserve so the CGA execution gate passes.
        contribute_reserve(20000000)
        executed = validate_success(api.execute_gift_agreement(agreement["id"], gift_admin_headers))
        # Identical gift economics under the 6% table book a different
        # deduction than the 5% illustration reported.
        assert executed["booked_deduction_cents"] == BOOKED_AGE70_RATE600_DEDUCTION_CENTS
        assert (
            executed["booked_deduction_cents"]
            != illustration["illustrated_deduction_cents"]
        )
