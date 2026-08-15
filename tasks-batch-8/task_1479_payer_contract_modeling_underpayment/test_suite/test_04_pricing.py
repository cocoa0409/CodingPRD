"""Claim intake and the expected-reimbursement pricing chain (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_claim_line,
    add_contract_term,
    add_stop_loss_provision,
    approve_amendment,
    assert_claim,
    create_amendment,
    create_draft_contract,
    create_escalator,
    create_test_claim,
    create_test_payer,
    list_claim_lines,
    price_claim,
    reprice_claim,
    set_clock,
    setup_active_contract,
    setup_priced_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AUD, CA, CM, RIA


class TestClaimIntake:
    def test_claim_creation_sets_system_fields(self, api):
        """PRD §3.5: "A new claim starts `UNPRICED` on its pricing dimension
        and `AWAITING_REMITTANCE` on its remittance dimension, with
        `network_flag` set to `NONE`; `priced_contract_id`,
        `network_agreement_id`, `pricing_variant`,
        `expected_reimbursement_cents`, and `original_expected_cents` all
        remain null until the first successful pricing run, and the two
        dimensions evolve independently from that point on."

        Design: Corner/entities/ent_claim_creation_sets_system_fields
        """
        payer = create_test_payer(name="Payer SF", payer_type="MEDICAID_MCO")
        claim = validate_success(
            api.create_claim(
                {
                    "payer_id": payer["id"],
                    "claim_number": "CL-SF1",
                    "patient_account_number": "PA-SF1",
                    "service_category": "LAB",
                    "admission_date": "2026-06-01",
                    "discharge_date": "2026-06-01",
                    "total_billed_charges_cents": 100,
                },
                RIA,
            ),
            expected_status=201,
        )
        assert_claim(claim)
        assert claim["pricing_status"] == "UNPRICED"
        assert claim["remittance_status"] == "AWAITING_REMITTANCE"
        assert claim["network_flag"] == "NONE"
        assert claim["expected_reimbursement_cents"] is None
        assert claim["original_expected_cents"] is None
        assert claim["version"] == 1

    def test_claim_future_discharge_rejected(self, api):
        """PRD §2.8 rung 3: "neither `discharge_date` nor `remittance_date`
        after today, ... else `ERR_INVALID_REQUEST`." PRD §2.4: the clock
        "boots to exactly `2026-08-01T00:00:00Z` at server startup".

        Design: Corner/entities/ent_claim_future_discharge_rejected
        """
        payer = create_test_payer(name="Payer FD")
        resp = api.create_claim(
            {
                "payer_id": payer["id"],
                "claim_number": "CL-FD1",
                "patient_account_number": "PA-FD1",
                "service_category": "LAB",
                "admission_date": "2026-06-01",
                "discharge_date": "2026-09-01",
                "total_billed_charges_cents": 100,
            },
            RIA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_duplicate_claim_number_rejected(self, api):
        """PRD §3.5: a claim names "a `claim_number` unique within that
        payer's book (`ERR_DUPLICATE_CLAIM_NUMBER`)".

        Design: Corner/errors/err_duplicate_claim_number_rejected
        """
        payer = create_test_payer(name="Payer DN")
        create_test_claim(
            payer["id"], claim_number="CL-DUP", patient_account_number="PA-DN1",
            service_category="LAB", admission_date="2026-06-01",
            discharge_date="2026-06-01", total_billed_charges_cents=100,
        )
        resp = api.create_claim(
            {
                "payer_id": payer["id"],
                "claim_number": "CL-DUP",
                "patient_account_number": "PA-DN2",
                "service_category": "IMAGING",
                "admission_date": "2026-06-02",
                "discharge_date": "2026-06-02",
                "total_billed_charges_cents": 200,
            },
            RIA,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM_NUMBER.value)

    def test_list_claims_filter_pagination_envelope(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope." PRD §3.5:
        "Claims may be listed filtered by `payer_id`, `priced_contract_id`,
        `network_agreement_id`, `pricing_status`, `remittance_status`, or
        `network_flag`."

        Design: Corner/entities/ent_list_claims_filter_pagination_envelope
        """
        payer = create_test_payer(name="Payer PG")
        for i in (1, 2, 3):
            create_test_claim(
                payer["id"],
                claim_number=f"CL-PG{i}",
                patient_account_number=f"PA-PG{i}",
                service_category="LAB",
                admission_date="2026-06-01",
                discharge_date="2026-06-01",
                total_billed_charges_cents=100,
            )
        page1, meta1 = validate_paginated(
            api.list_claims(AUD, params={"payer_id": payer["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_claims(AUD, params={"payer_id": payer["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for item in page1 + page2:
            assert item["payer_id"] == payer["id"]


class TestPricingPreconditions:
    def test_line_addition_after_pricing_rejected(self, api):
        """PRD §3.5: "While the claim is `UNPRICED`, the analyst adds lines
        beneath it — attempting to add a line after pricing is rejected with
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/sm_line_addition_after_pricing_rejected
        """
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-LP1"})
        resp = api.add_claim_line(
            ctx["claim"]["id"],
            {
                "revenue_code": "0101",
                "service_date": "2026-06-02",
                "charge_cents": 5000,
                "units": 1,
            },
            RIA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert len(list_claim_lines(ctx["claim"]["id"])) == 1

    def test_line_outside_stay_rejected(self, api):
        """PRD §3.5: each line carries "a `service_date` that must lie inside
        the stay from `admission_date` through `discharge_date` inclusive
        (`ERR_LINE_OUTSIDE_STAY`)".

        Design: Corner/errors/err_line_outside_stay_rejected
        """
        payer = create_test_payer(name="Payer LO")
        claim = create_test_claim(payer["id"], claim_number="CL-LO1")
        resp = api.add_claim_line(
            claim["id"],
            {
                "revenue_code": "0100",
                "service_date": "2026-06-04",
                "charge_cents": 100000,
                "units": 1,
            },
            RIA,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_OUTSIDE_STAY.value)
        assert list_claim_lines(claim["id"]) == []

    def test_no_matching_term_on_price(self, api):
        """PRD §3.5: "the pricing run then requires a matching term on the
        resolved contract (`ERR_NO_MATCHING_TERM`)".

        Design: Corner/errors/err_no_matching_term_on_price
        """
        ctx = setup_active_contract()  # only an INPATIENT_MEDICAL term
        claim = create_test_claim(
            ctx["payer"]["id"],
            claim_number="CL-NM1",
            service_category="EMERGENCY",
            admission_date="2026-06-10",
            discharge_date="2026-06-10",
            total_billed_charges_cents=90000,
        )
        add_claim_line(
            claim["id"], revenue_code="0450", service_date="2026-06-10",
            charge_cents=90000,
        )
        resp = api.price_claim(claim["id"], RIA)
        validate_error(resp, ApiErrorId.ERR_NO_MATCHING_TERM.value)
        claim_after = validate_success(api.get_claim(claim["id"], RIA))
        assert claim_after["pricing_status"] == "UNPRICED"

    def test_missing_drg_weight_on_price(self, api):
        """PRD §3.5: "when the resolved term's model is `DRG_BASE`, a present
        `drg_weight` (`ERR_MISSING_DRG_WEIGHT`)" is required at price time.

        Design: Corner/errors/err_missing_drg_weight_on_price
        """
        ctx = setup_active_contract(
            service_category="INPATIENT_SURGICAL", rate_model="DRG_BASE"
        )
        claim = create_test_claim(
            ctx["payer"]["id"],
            claim_number="CL-DW1",
            service_category="INPATIENT_SURGICAL",
            admission_date="2026-06-10",
            discharge_date="2026-06-12",
            total_billed_charges_cents=300000,
        )
        add_claim_line(
            claim["id"], revenue_code="0360", service_date="2026-06-10",
            charge_cents=300000,
        )
        resp = api.price_claim(claim["id"], RIA)
        validate_error(resp, ApiErrorId.ERR_MISSING_DRG_WEIGHT.value)
        claim_after = validate_success(api.get_claim(claim["id"], RIA))
        assert claim_after["pricing_status"] == "UNPRICED"

    def test_claim_has_no_lines_on_price(self, api):
        """PRD §3.5: pricing requires "at least one claim line
        (`ERR_CLAIM_HAS_NO_LINES`)".

        Design: Corner/errors/err_claim_has_no_lines_on_price
        """
        ctx = setup_active_contract()
        claim = create_test_claim(ctx["payer"]["id"], claim_number="CL-NL1")
        resp = api.price_claim(claim["id"], RIA)
        validate_error(resp, ApiErrorId.ERR_CLAIM_HAS_NO_LINES.value)
        claim_after = validate_success(api.get_claim(claim["id"], RIA))
        assert claim_after["pricing_status"] == "UNPRICED"


class TestBaseRateModels:
    def test_per_diem_counts_nights_not_days(self, api):
        """PRD §3.5: "Under `PER_DIEM`, the covered days are the calendar-day
        difference between `discharge_date` and `admission_date`, with a floor
        of one day, and each day earns the term's `base_rate_cents` with
        escalation applied per day as described below."

        Design: Corner/calculations/calc_per_diem_counts_nights_not_days
        """
        ctx = setup_priced_claim(
            claim_overrides={
                "claim_number": "CL-ND1",
                "admission_date": "2026-06-01",
                "discharge_date": "2026-06-04",
                "total_billed_charges_cents": 600000,
            },
            lines=[{"revenue_code": "0100", "service_date": "2026-06-02",
                    "charge_cents": 600000, "units": 1}],
        )
        # 2026-06-01..2026-06-04 -> 3 nights x 100000 (discharge day excluded).
        assert ctx["claim"]["expected_reimbursement_cents"] == 300000

    def test_drg_base_weight_rounding(self, api):
        """PRD §3.5: "Under `DRG_BASE`, the base is the term's
        `base_rate_cents` multiplied by the claim's `drg_weight`, rounded half
        up to whole cents."

        Design: Corner/calculations/calc_drg_base_weight_rounding
        """
        ctx = setup_priced_claim(
            service_category="INPATIENT_SURGICAL",
            rate_model="DRG_BASE",
            base_rate_cents=100001,
            claim_overrides={
                "claim_number": "CL-DG1",
                "admission_date": "2026-06-10",
                "discharge_date": "2026-06-12",
                "total_billed_charges_cents": 400000,
                "drg_weight": 1.005,
            },
            lines=[{"revenue_code": "0360", "service_date": "2026-06-10",
                    "charge_cents": 400000, "units": 1}],
        )
        # round_half_up(100001 * 1.005) = round_half_up(100501.005) = 100501.
        assert ctx["claim"]["expected_reimbursement_cents"] == 100501

    def test_volume_tier_inclusive_boundary(self, api):
        """PRD §3.5: "The selected tier is the entry with the greatest
        `min_annual_units` that the trailing units reach or exceed — a
        trailing count exactly equal to a tier's minimum selects that tier —
        and when no tier qualifies there is no adjustment." The measurement
        excludes "the claim currently being priced".

        Design: Corner/calculations/calc_volume_tier_inclusive_boundary
        """
        ctx = setup_active_contract(
            service_category="OUTPATIENT_SURGERY",
            rate_model="CASE_RATE",
            base_rate_cents=100000,
            contract_overrides={
                "contract_code": "VT-2026",
                "volume_tiers": [
                    {
                        "service_category": "OUTPATIENT_SURGERY",
                        "min_annual_units": 2,
                        "rate_adjustment_bp": 1000,
                    }
                ],
            },
        )
        claims = []
        for suffix, day in (("A", "01"), ("B", "02"), ("C", "03")):
            claim = create_test_claim(
                ctx["payer"]["id"],
                claim_number=f"CL-VT{suffix}",
                service_category="OUTPATIENT_SURGERY",
                admission_date=f"2026-06-{day}",
                discharge_date=f"2026-06-{day}",
                total_billed_charges_cents=150000,
            )
            add_claim_line(
                claim["id"], revenue_code="0360",
                service_date=f"2026-06-{day}", charge_cents=150000,
            )
            claims.append(claim)
        priced_a = price_claim(claims[0]["id"])
        priced_b = price_claim(claims[1]["id"])
        priced_c = price_claim(claims[2]["id"])
        assert priced_a["expected_reimbursement_cents"] == 100000  # U=0
        assert priced_b["expected_reimbursement_cents"] == 100000  # U=1
        # U=2 == min_annual_units selects the tier: round(100000 * 1.1).
        assert priced_c["expected_reimbursement_cents"] == 110000
        assert priced_c["pricing_trace"]["volume_tier_bp"] == 1000


class TestEscalatorPricing:
    def test_escalator_mid_stay_proration(self, api):
        """PRD §3.5: "Per-diem stays prorate mid-stay effective dates: each
        calendar day from `admission_date` through the day before
        `discharge_date` gets its own multiplier, computed over only those
        escalators whose `effective_date` is on or before that day, and each
        day's rate — the per-diem rate times that day's multiplier — is
        rounded half up to whole cents before the day rates sum to the
        escalated base."

        Design: Corner/calculations/calc_escalator_mid_stay_proration
        """
        payer = create_test_payer(name="Payer EP")
        contract = create_draft_contract(payer["id"], contract_code="EP-2026")
        add_contract_term(contract["id"])
        create_escalator(
            contract["id"], effective_date="2026-06-03", escalator_bp=2000,
            compounding=True,
        )
        activate_contract(contract["id"])
        set_clock("2026-08-01T00:00:00Z")  # applies the escalator
        claim = create_test_claim(
            payer["id"],
            claim_number="CL-EP1",
            admission_date="2026-06-01",
            discharge_date="2026-06-04",
            total_billed_charges_cents=600000,
        )
        add_claim_line(claim["id"], charge_cents=600000)
        priced = price_claim(claim["id"])
        # Days 06-01/06-02 at 100000, day 06-03 at 120000 -> 320000.
        assert priced["expected_reimbursement_cents"] == 320000

    def test_compounding_vs_additive_escalators(self, api):
        """PRD §3.5: "A running multiplier starts at 1; each compounding
        escalator multiplies it by one plus its `escalator_bp` divided by
        10000, while each non-compounding escalator instead adds its
        `escalator_bp` divided by 10000 to the running multiplier."

        Design: Corner/calculations/calc_compounding_vs_additive_escalators
        """

        def build(compounding: bool, code: str):
            payer = create_test_payer(name=f"Payer {code}")
            contract = create_draft_contract(payer["id"], contract_code=f"{code}-2026")
            add_contract_term(
                contract["id"], service_category="OBSERVATION",
                rate_model="CASE_RATE", base_rate_cents=100000,
            )
            create_escalator(contract["id"], effective_date="2026-06-01",
                             escalator_bp=1000, compounding=compounding)
            create_escalator(contract["id"], effective_date="2026-06-02",
                             escalator_bp=1000, compounding=compounding)
            activate_contract(contract["id"])
            return payer

        payer_cmp = build(True, "CMP")
        payer_add = build(False, "ADD")
        set_clock("2026-08-01T00:00:00Z")  # applies all four escalators

        def price_one(payer, number):
            claim = create_test_claim(
                payer["id"], claim_number=number, service_category="OBSERVATION",
                admission_date="2026-06-05", discharge_date="2026-06-05",
                total_billed_charges_cents=200000,
            )
            add_claim_line(claim["id"], revenue_code="0760",
                           service_date="2026-06-05", charge_cents=200000)
            return price_claim(claim["id"])

        priced_cmp = price_one(payer_cmp, "CL-CMP1")
        priced_add = price_one(payer_add, "CL-ADD1")
        # Compounding: 100000 * 1.1 * 1.1 = 121000; additive: 100000 * 1.2.
        assert priced_cmp["expected_reimbursement_cents"] == 121000
        assert priced_add["expected_reimbursement_cents"] == 120000
        assert priced_cmp["expected_reimbursement_cents"] != priced_add[
            "expected_reimbursement_cents"
        ]


class TestPercentOfChargeRounding:
    """PERCENT_OF_CHARGE pins round-per-line-THEN-sum (PRD §2.6, §3.5)."""

    def _setup_three_penny_claim(self, api):
        ctx = setup_active_contract(
            service_category="LAB",
            rate_model="PERCENT_OF_CHARGE",
            base_rate_cents=None,
            percent_of_charge_bp=5000,
            contract_overrides={"contract_code": "RC-2026"},
        )
        claim = create_test_claim(
            ctx["payer"]["id"],
            claim_number="CL-RC1",
            service_category="LAB",
            admission_date="2026-06-01",
            discharge_date="2026-06-01",
            total_billed_charges_cents=3,
        )
        for rev in ("0300", "0301", "0302"):
            add_claim_line(claim["id"], revenue_code=rev, charge_cents=1)
        return ctx, claim

    def test_percent_of_charge_round_per_line_then_sum(self, api):
        """PRD §3.5: "Under `PERCENT_OF_CHARGE`, each non-carved line
        contributes its `charge_cents` multiplied by the term's
        `percent_of_charge_bp` and divided by 10000, rounded half up per line,
        and the base is the sum of those line amounts — the system rounds per
        line and then sums, never sums and then rounds."

        Design: Difficulty/combinatorial_formula/percent_of_charge_round_per_line_then_sum
        """
        _ctx, claim = self._setup_three_penny_claim(api)
        priced = price_claim(claim["id"])
        # 3 x round_half_up(1 * 5000/10000) = 3 x 1 = 3; the forbidden
        # sum-then-round order would give round_half_up(1.5) = 2.
        assert priced["expected_reimbursement_cents"] == 3
        assert priced["expected_reimbursement_cents"] != 2
        lines = list_claim_lines(claim["id"])
        assert len(lines) == 3
        for line in lines:
            assert line["priced_amount_cents"] == 1

    def test_percent_of_charge_trace_records_rounded_base(self, api):
        """PRD §3.5: "Every pricing run leaves an audit trail in the claim's
        `pricing_trace`: the `resolution_path` taken, the winning
        `contract_id` and `term_id`, the `base_amount_cents`, the
        `escalated_amount_cents`, the applied `volume_tier_bp`, the
        `carve_out_cents`, `outlier_cents`, and `stop_loss_cents` overlays,
        the `wrap_rate_bp` on the wrap path, and the `final_expected_cents`."

        Design: Difficulty/combinatorial_formula/percent_of_charge_round_per_line_then_sum
        """
        ctx, claim = self._setup_three_penny_claim(api)
        priced = price_claim(claim["id"])
        trace = priced["pricing_trace"]
        assert trace["base_amount_cents"] == 3
        assert trace["final_expected_cents"] == 3
        assert trace["contract_id"] == ctx["contract"]["id"]
        assert priced["pricing_variant"] == "PROSPECTIVE"


class TestStopLossOutlierOverlay:
    """Outlier -> subtotal -> stop-loss max() pinned order (PRD §3.5)."""

    def _setup_overlay_claim(self, api):
        payer = create_test_payer(name="Payer SL")
        contract = create_draft_contract(payer["id"], contract_code="SL-2026")
        add_contract_term(
            contract["id"], service_category="EMERGENCY",
            rate_model="CASE_RATE", base_rate_cents=100000,
        )
        add_stop_loss_provision(
            contract["id"], provision_type="OUTLIER",
            threshold_cents=500000, rate_bp=8000,
        )
        add_stop_loss_provision(
            contract["id"], provision_type="STOP_LOSS",
            threshold_cents=1000000, rate_bp=9000,
        )
        activate_contract(contract["id"])
        claim = create_test_claim(
            payer["id"], claim_number="CL-SL1", service_category="EMERGENCY",
            admission_date="2026-06-10", discharge_date="2026-06-10",
            total_billed_charges_cents=3000000,
        )
        add_claim_line(claim["id"], revenue_code="0450",
                       service_date="2026-06-10", charge_cents=3000000)
        return claim

    def test_overlay_computes_outlier_and_stop_loss_amounts(self, api):
        """PRD §3.5: "Outlier first: ... if `total_billed_charges_cents`
        reaches or exceeds its `threshold_cents`, the outlier amount is the
        excess of total charges over the threshold, multiplied by `rate_bp`
        and divided by 10000, rounded half up; otherwise the outlier amount
        is zero." and "if the applicable `STOP_LOSS` provision — again
        category-specific beats wildcard — has its `threshold_cents` met or
        exceeded by `total_billed_charges_cents`, the floor is total charges
        times `rate_bp` divided by 10000, rounded half up".

        Design: Difficulty/combinatorial_formula/stop_loss_outlier_overlay_max_floor_interaction
        """
        claim = self._setup_overlay_claim(api)
        priced = price_claim(claim["id"])
        trace = priced["pricing_trace"]
        # outlier = round((3000000 - 500000) * 0.8) = 2000000.
        assert trace["outlier_cents"] == 2000000
        # stop-loss floor = round(3000000 * 0.9) = 2700000.
        assert trace["stop_loss_cents"] == 2700000

    def test_overlay_final_is_max_of_subtotal_and_floor(self, api):
        """PRD §3.5: "The subtotal is then the tiered base plus the carve-out
        total plus the outlier amount. Stop-loss second: ... the final
        expected amount is the greater of the subtotal and that floor;
        otherwise the final amount is the subtotal."

        Design: Difficulty/combinatorial_formula/stop_loss_outlier_overlay_max_floor_interaction
        """
        claim = self._setup_overlay_claim(api)
        priced = price_claim(claim["id"])
        # max(100000 + 0 + 2000000, 2700000) = 2700000 — the floor wins.
        assert priced["expected_reimbursement_cents"] == 2700000
        assert priced["pricing_trace"]["final_expected_cents"] == 2700000


class TestStopLossBoundary:
    def _setup_stop_loss_contract(self, api):
        payer = create_test_payer(name="Payer BS")
        contract = create_draft_contract(payer["id"], contract_code="BS-2026")
        add_contract_term(
            contract["id"], service_category="EMERGENCY",
            rate_model="CASE_RATE", base_rate_cents=100000,
        )
        add_stop_loss_provision(
            contract["id"], provision_type="STOP_LOSS",
            threshold_cents=500000, rate_bp=9000,
        )
        activate_contract(contract["id"])
        return payer

    def _price_billed(self, payer, number, billed):
        claim = create_test_claim(
            payer["id"], claim_number=number, service_category="EMERGENCY",
            admission_date="2026-06-10", discharge_date="2026-06-10",
            total_billed_charges_cents=billed,
        )
        add_claim_line(claim["id"], revenue_code="0450",
                       service_date="2026-06-10", charge_cents=billed)
        return price_claim(claim["id"])

    def test_stop_loss_charges_exactly_at_threshold_pays_floor(self, api):
        """PRD §3.5: "if the applicable `STOP_LOSS` provision — again
        category-specific beats wildcard — has its `threshold_cents` met or
        exceeded by `total_billed_charges_cents`, the floor is total charges
        times `rate_bp` divided by 10000, rounded half up, and the final
        expected amount is the greater of the subtotal and that floor" and
        "Both triggers use inclusive boundaries."

        Design: Difficulty/boundary_precision_check/stop_loss_charges_exactly_at_threshold_pays_floor
        """
        payer = self._setup_stop_loss_contract(api)
        priced = self._price_billed(payer, "CL-BS1", 500000)
        # billed == threshold triggers: max(100000, round(500000 * 0.9)).
        assert priced["expected_reimbursement_cents"] == 450000
        assert priced["pricing_trace"]["stop_loss_cents"] == 450000

    def test_stop_loss_charges_one_cent_below_threshold_no_floor(self, api):
        """PRD §3.5: "Both triggers use inclusive boundaries." — one cent
        below the threshold, "otherwise the final amount is the subtotal"
        applies and the floor does not engage.

        Design: Difficulty/boundary_precision_check/stop_loss_charges_exactly_at_threshold_pays_floor
        """
        payer = self._setup_stop_loss_contract(api)
        priced = self._price_billed(payer, "CL-BS2", 499999)
        assert priced["expected_reimbursement_cents"] == 100000


class TestProspectiveVsRetrospective:
    """PROSPECTIVE snapshot vs RETROSPECTIVE reprice under an amendment."""

    def _setup_priced_then_amended(self, api):
        """Price a 2-night PER_DIEM claim at 200000, then make a 120000/day
        amendment EFFECTIVE (effective 2026-06-01, no retroactive_to_date)."""
        ctx = setup_priced_claim(claim_overrides={"claim_number": "CL-DV1"})
        assert ctx["claim"]["expected_reimbursement_cents"] == 200000
        amendment = create_amendment(
            ctx["contract"]["id"],
            ctx["contract_version"],
            creator_user_id="ca-1",
            effective_date="2026-06-01",
            term_overrides=[
                {"service_category": "INPATIENT_MEDICAL", "base_rate_cents": 120000}
            ],
        )
        approve_amendment(amendment["id"], approver_user_id="cm-2")
        set_clock("2026-08-02T00:00:00Z")  # sweep applies the amendment
        ctx["amendment"] = amendment
        return ctx

    def test_reprice_diverges_from_frozen_prospective_snapshot(self, api):
        """PRD §3.5: "A successful first pricing moves the claim to `PRICED`
        and stamps `pricing_variant` to `PROSPECTIVE`: it sets
        `expected_reimbursement_cents`, freezes the same figure into
        `original_expected_cents` — an immutable snapshot no later run may
        overwrite". PRD §3.5: "A reprice overwrites
        `expected_reimbursement_cents` and refreshes `pricing_trace`, but
        never touches `original_expected_cents`; identical claim data yields
        a different number whenever the effective rate set changed between
        the two runs."

        Design: Difficulty/dual_variant_calc/prospective_vs_retrospective_repricing_diverges
        """
        ctx = self._setup_priced_then_amended(api)
        repriced = reprice_claim(ctx["claim"]["id"])
        assert repriced["original_expected_cents"] == 200000
        assert repriced["expected_reimbursement_cents"] == 240000
        assert repriced["pricing_variant"] == "RETROSPECTIVE"
        assert repriced["pricing_status"] == "REPRICED"
        assert repriced["original_expected_cents"] != repriced[
            "expected_reimbursement_cents"
        ]

    def test_retrospective_reprice_uses_current_rate_set(self, api):
        """PRD §3.5: repricing "runs with `pricing_variant` set to
        `RETROSPECTIVE`: the pricing chain executes against the current
        amendment chain, whose retroactive overrides reach back to their
        `retroactive_to_date`, and the current set of `APPLIED` escalators."

        Design: Difficulty/dual_variant_calc/prospective_vs_retrospective_repricing_diverges
        """
        ctx = self._setup_priced_then_amended(api)
        repriced = reprice_claim(ctx["claim"]["id"])
        # 2 nights x 120000 amended rate; trace reflects the current run.
        assert repriced["pricing_trace"]["final_expected_cents"] == 240000
        # A second reprice under an unchanged rate set yields the same number;
        # the frozen snapshot still never moves.
        repriced2 = reprice_claim(ctx["claim"]["id"])
        assert repriced2["expected_reimbursement_cents"] == 240000
        assert repriced2["original_expected_cents"] == 200000
