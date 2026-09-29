"""Pinned arithmetic: penalty floors, bond bases, allocation rounding and waterfalls."""

from test_helpers import (
    TAX_SUPERVISOR_ID,
    ApiErrorId,
    assert_assessment_money,
    assert_bond_position,
    assert_case_dimensions,
    assert_claim_money,
    assert_gallons,
    assert_ledger_row,
    assert_ledger_sequence,
    assert_return_money,
    assert_return_statuses,
    assert_total_count,
    cents_for,
    ids_of,
    refund_cents_for,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    inspection_payload,
    licensee_payload,
    refund_claim_payload,
)


class TestPenaltyAndBondArithmetic:
    def test_a_small_tank_pays_the_dyed_penalty_floor_rather_than_the_per_gallon_figure(
        self, api, world, inspector_headers, officer_headers
    ):
        """40.00 gallons computes 40000 cents, so the 100000-cent floor decides a first offence.

        PRD: "A base amount is taken as the **greater** of a flat 100000 cents and
        `gallons_in_tank` multiplied by 1000 cents per gallon rounded half up."
        PRD: "Hop one is the assessment itself: `prior_positive_count` and `penalty_cents` are
        frozen, `status` becomes `PENALTY_ASSESSED`, a `PENALTY` ledger entry for the positive
        `penalty_cents` is appended naming the inspection as its source, the licensee's
        `balance_cents` is re-derived, and the licensee's `dyed_violation_count` increases by one."
        PRD: "Hop two fires only if that new count reaches the suspension threshold of 2 **and**
        the licensee's `status` is `ACTIVE`: the licensee is driven to `SUSPENDED`."

        Design: Corner/calculations/dyed_penalty_floor_dominates_a_small_tank
        """
        retailer = world.new_licensee(
            "RETAILER", legal_name="Floor Test Retail Stops LLC", retail_channel="HIGHWAY"
        )

        response = api.create_inspection(
            inspection_payload(
                retailer["id"],
                dye_test_result="POSITIVE",
                gallons_in_tank=40.00,
                inspection_date="2026-07-20",
                vehicle_identifier="MN-TRK-9001",
                location_description="I-94 eastbound scale",
            ),
            inspector_headers,
        )

        inspection = validate_success(response, expected_status=201)
        assert inspection["prior_positive_count"] == 0
        assert inspection["penalty_cents"] == 100000
        assert inspection["status"] == "PENALTY_ASSESSED"

        licensee = world.licensee(retailer["id"])
        assert licensee["dyed_violation_count"] == 1
        assert licensee["balance_cents"] == 100000
        assert licensee["status"] == "PENDING_BOND"

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                retailer["id"], officer_headers, params={"entry_type": "PENALTY"}
            )
        )
        assert_total_count(meta, 1, "PENALTY ledger total_count")
        assert_ledger_row(
            rows[0],
            "PENALTY",
            100000,
            source_entity_type="RoadsideInspection",
            source_entity_id=inspection["id"],
        )

    def test_the_bond_basis_counts_only_filed_returns(
        self, api, world, officer_headers, examiner_headers
    ):
        """A draft sibling return carrying 100000.00 gallons cannot move the bond basis.

        PRD: "The system takes the **newest up to three** monthly returns of the licensee whose
        `filing_status` is `FILED`, ordered by `period_month` descending with ties broken by
        `created_at` ascending; draft and superseded returns are invisible to this basis."
        PRD: "A dedicated computed read exposes `avg_monthly_tax_liability_cents`,
        `required_bond_cents`, `posted_bond_cents`, `bond_deficiency_cents` and
        `basis_return_count`, the last being how many filed returns actually entered the average
        (0, 1, 2 or 3)."

        Design: Corner/calculations/bond_basis_excludes_a_draft_return
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Basis Fuel Supply LLC")
        distributor = world.active_licensee(
            "DISTRIBUTOR", bond_cents=1500000, legal_name="Basis Distribution Inc"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        filed = world.filed_return(
            distributor["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 17482.52,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 17482.52,
                            "date": "2026-08-05",
                        }
                    ],
                }
            ],
            attest_name="B. Basis",
        )
        assert_return_money(filed.row, tax_due_cents=500000, days_late=0)
        assert cents_for(17482.52, "GASOLINE") == 500000
        draft = world.build_return(
            distributor["id"],
            "2026-07",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 100000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100000.00,
                            "date": "2026-07-05",
                        }
                    ],
                }
            ],
        )

        response = api.get_bond_status(distributor["id"], officer_headers)

        status = validate_success(response, expected_status=200)
        assert status["basis_return_count"] == 1
        assert_bond_position(
            status,
            required_bond_cents=1500000,
            posted_bond_cents=1500000,
            bond_deficiency_cents=0,
            avg_monthly_tax_liability_cents=500000,
        )

        draft_reread = validate_success(api.get_return(draft.id, examiner_headers))
        assert_return_statuses(draft_reread, "DRAFT", "NOT_MATCHED")

        licensee = world.licensee(distributor["id"])
        assert_bond_position(licensee, avg_monthly_tax_liability_cents=500000)
        assert licensee["balance_cents"] == 500000

    def test_the_licence_type_multiplier_decides_the_requirement_before_the_clamp(
        self, api, world, officer_headers
    ):
        """The same assumed liability produces 400000 for a RETAILER and 1500000 for a SUPPLIER.

        PRD: "That average is then multiplied by three months of coverage, by a multiplier keyed on
        `license_type` — 1.0 for `SUPPLIER`, `DISTRIBUTOR` and `BLENDER`, 0.5 for `TRANSPORTER`,
        0.25 for `RETAILER` — and by a suspension multiplier of 2.0 while the licensee's `status`
        is `SUSPENDED` and 1.0 otherwise."
        PRD: "The product is rounded **up** to the next whole multiple of 100000 cents, and only
        then clamped into the statutory band: `required_bond_cents` is the clamped value, never
        below 200000 cents and never above 100000000 cents."

        Design: Corner/calculations/type_multiplier_constants_set_retailer_and_supplier_requirements
        """
        retailer_response = api.create_licensee(
            licensee_payload("RETAILER", legal_name="Multiplier Retail Stops LLC"),
            officer_headers,
        )
        supplier_response = api.create_licensee(
            licensee_payload("SUPPLIER", legal_name="Multiplier Fuel Supply LLC"),
            officer_headers,
        )

        retailer = validate_success(retailer_response, expected_status=201)
        supplier = validate_success(supplier_response, expected_status=201)

        assert_bond_position(
            retailer,
            required_bond_cents=400000,
            posted_bond_cents=0,
            bond_deficiency_cents=400000,
            avg_monthly_tax_liability_cents=500000,
        )
        assert_bond_position(
            supplier,
            required_bond_cents=1500000,
            posted_bond_cents=0,
            bond_deficiency_cents=1500000,
            avg_monthly_tax_liability_cents=500000,
        )

        status = validate_success(api.get_bond_status(retailer["id"], officer_headers))
        assert status["basis_return_count"] == 0
        assert_bond_position(status, required_bond_cents=400000)


class TestRefundArithmetic:
    def test_the_pto_allocation_is_rounded_to_gallons_before_the_rate_is_applied(
        self, api, world, examiner_headers, officer_headers
    ):
        """99.999 allocated gallons become 100.00 first, so the refund is 3090 cents and not 3089.

        PRD: "For a `PTO` claim the basis is `claimed_gallons` multiplied by the allocation
        percentage for the named equipment class — 0.30 for `CONCRETE_MIXER`, 0.25 for
        `REFUSE_PACKER`, 0.15 for `BULK_TANKER_PUMP` — rounded half up to two decimals."
        PRD: "`refund_amount_cents` is `allowable_gallons` multiplied by 30.9 cents per gallon,
        rounded half up to a whole cent, exactly once."
        PRD: "The gallons rounding of step one happens before this multiplication, never after it."

        Design: Corner/calculations/pto_allocation_rounds_half_up_before_the_money_step
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Reefer Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Mixer Ready Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        world.filed_return(
            claimant["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 500.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 500.00,
                            "date": "2026-08-11",
                        }
                    ],
                }
            ],
            attest_name="M. Mixer",
        )

        response = api.create_refund_claim(
            refund_claim_payload(
                claimant["id"],
                "2026-08",
                333.33,
                claim_type="PTO",
                equipment_class="CONCRETE_MIXER",
            ),
            examiner_headers,
        )

        claim = validate_success(response, expected_status=201)
        assert_claim_money(claim, 100.00, 3090)
        assert refund_cents_for(100.00) == 3090
        assert claim["status"] == "SUBMITTED"
        assert claim["equipment_class"] == "CONCRETE_MIXER"

        _rows, meta = validate_paginated(
            api.list_ledger_entries(claimant["id"], officer_headers)
        )
        assert_total_count(meta, 1, "ledger total_count for a zero-tax filing plus a new claim")

    def test_a_second_claim_over_the_remaining_pool_is_refused_not_clamped(
        self, api, world, examiner_headers
    ):
        """60.00 claimed gallons leave 40.00 available, so a 50.00-gallon claim is rejected outright.

        PRD: "Against that pool the system subtracts the gallons already consumed: the sum of
        `allowable_gallons` over the claimant's other claims for the same period whose `status` is
        anything other than `DENIED`, walked in ascending `created_at` order."
        PRD: "If the new claim's basis exceeds what remains, the claim is **rejected** with
        `ERR_REFUND_EXCEEDS_TAX_PAID` (HTTP 422); it is never silently reduced to fit."

        Design: Corner/calculations/second_claim_over_the_remaining_pool_returns_refund_exceeds_tax_paid
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Waterfall Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Waterfall Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        world.filed_return(
            claimant["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 100.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.00,
                            "date": "2026-08-11",
                        }
                    ],
                }
            ],
            attest_name="W. Waterfall",
        )
        first_claim = world.refund_claim(claimant["id"], "2026-08", 60.00)

        response = api.create_refund_claim(
            refund_claim_payload(claimant["id"], "2026-08", 50.00), examiner_headers
        )

        validate_error(response, ApiErrorId.REFUND_EXCEEDS_TAX_PAID, expected_status=422)
        rows, meta = validate_paginated(
            api.list_refund_claims(examiner_headers, params={"licensee_id": claimant["id"]})
        )
        assert_total_count(meta, 1, "refund claim total_count after the refused claim")
        assert ids_of(rows) == [first_claim["id"]]

        survivor = validate_success(
            api.get_refund_claim(first_claim["id"], examiner_headers)
        )
        assert_claim_money(survivor, 60.00, 1854)
        assert refund_cents_for(60.00) == 1854

        exactly_the_remainder = validate_success(
            api.create_refund_claim(
                refund_claim_payload(claimant["id"], "2026-08", 40.00), examiner_headers
            ),
            expected_status=201,
        )
        assert_claim_money(exactly_the_remainder, 40.00, refund_cents_for(40.00))


class TestCrossMatchInputSet:
    def test_two_supplier_lines_collapse_into_one_cell_and_a_draft_return_contributes_none(
        self, api, world, officer_headers
    ):
        """100.00 plus 3000.00 is one 3100.00-gallon cell, and an unfiled return is not a cell at all.

        PRD: "Only returns whose `filing_status` is `FILED` and whose `period_month` equals the
        run's `period_month` enter either side of the comparison; draft and superseded returns are
        invisible to cross-matching."
        PRD: "For each such cell the run computes `supplier_gallons` as the exact two-decimal sum of
        that supplier's `SCH_5_DELIVERED_TAX_COLLECTED` line gallons naming this counterparty and
        product."
        PRD: "Every cell examined increments `matched_cells_count`, whether or not it produces a
        finding."

        Design: Corner/calculations/cross_match_sums_lines_per_cell_and_ignores_a_draft_supplier_return
        """
        supplier_one = world.new_licensee("SUPPLIER", legal_name="Cell Sum Fuel Supply LLC")
        supplier_two = world.new_licensee("SUPPLIER", legal_name="Invisible Draft Supply LLC")
        distributor = world.new_licensee("DISTRIBUTOR", legal_name="Cell Sum Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        supplier_filed = world.filed_return(
            supplier_one["id"],
            "2026-08",
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": "GASOLINE",
                    "total": 3100.00,
                    "lines": [
                        {
                            "counterparty": distributor["id"],
                            "gallons": 100.00,
                            "date": "2026-08-03",
                            "transaction_type": "SALE",
                        },
                        {
                            "counterparty": distributor["id"],
                            "gallons": 3000.00,
                            "date": "2026-08-17",
                            "transaction_type": "SALE",
                        },
                    ],
                }
            ],
            attest_name="C. Cellsum",
        )
        supplier_draft = world.build_return(
            supplier_two["id"],
            "2026-08",
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": "GASOLINE",
                    "total": 800.00,
                    "lines": [
                        {
                            "counterparty": distributor["id"],
                            "gallons": 800.00,
                            "date": "2026-08-19",
                            "transaction_type": "SALE",
                        }
                    ],
                }
            ],
        )
        purchaser_filed = world.filed_return(
            distributor["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "GASOLINE",
                    "total": 3100.00,
                    "lines": [
                        {
                            "counterparty": supplier_one["id"],
                            "gallons": 3100.00,
                            "date": "2026-08-17",
                        }
                    ],
                }
            ],
            attest_name="C. Cellsum Dist",
        )

        response = api.create_cross_match_run({"period_month": "2026-08"}, world.examiner)

        run = validate_success(response, expected_status=201)
        assert run["matched_cells_count"] == 1, (
            "the supplier's two lines are one counterparty-and-product cell, "
            f"got matched_cells_count {run['matched_cells_count']}"
        )
        assert run["discrepancy_count"] == 0
        assert run["escalated_count"] == 0
        assert run["escalation_skipped_count"] == 0
        assert_gallons(run["gross_unreported_gallons_total"], 0.00, "gross_unreported_gallons_total")
        assert_gallons(run["unreported_gallons_total"], 0.00, "unreported_gallons_total")
        assert_gallons(run["tolerance_gallons"], 5.00, "tolerance_gallons")

        _rows, meta = validate_paginated(
            api.list_discrepancies(world.examiner, params={"run_id": run["id"]})
        )
        assert_total_count(meta, 0, "discrepancies for a cell that balances exactly")

        supplier_reread = validate_success(api.get_return(supplier_filed.id, world.examiner))
        purchaser_reread = validate_success(api.get_return(purchaser_filed.id, world.examiner))
        assert_return_statuses(supplier_reread, "FILED", "MATCH_CLEAN")
        assert_return_statuses(purchaser_reread, "FILED", "MATCH_CLEAN")

        draft_reread = validate_success(api.get_return(supplier_draft.id, world.examiner))
        assert_return_statuses(draft_reread, "DRAFT", "NOT_MATCHED")

        subject = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert subject["open_discrepancy_count"] == 0
        assert_gallons(subject["unreported_gallons_total"], 0.00, "unreported_gallons_total")


class TestAmendmentArithmetic:
    def test_an_amendment_that_lowers_tax_copies_the_interest_and_penalty_verbatim(
        self, api, world, officer_headers
    ):
        """286000 does not exceed 500000, so the late original's 1875 and 25094 are carried across.

        PRD: "And if the amendment's own `tax_due_cents` is less than or equal to the amended
        return's `tax_due_cents`, then `interest_cents` and `penalty_cents` are copied verbatim from
        the amended return rather than recomputed — a corrective amendment that does not increase tax
        cannot manufacture new penalty, and `amendment_delta_cents` therefore equals the pure tax
        difference."
        PRD: "For an **amendment**, exactly one entry is appended instead: a
        `RETURN_TAX_ADJUSTMENT` for `amendment_delta_cents`, and it is appended even when the delta
        is zero."

        Design: Corner/calculations/amendment_without_a_tax_increase_copies_penalty_and_interest
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Amend Fuel Supply LLC")
        filer = world.new_licensee("DISTRIBUTOR", legal_name="Amend Distribution Inc")
        world.set_clock("2026-10-05T00:00:00Z")
        original = world.filed_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 17482.52,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 17482.52,
                            "date": "2026-08-08",
                        }
                    ],
                }
            ],
            attest_name="A. Amend",
        )
        assert_return_money(
            original.row,
            tax_due_cents=500000,
            interest_cents=1875,
            penalty_cents=25094,
            total_remittance_cents=526969,
            days_late=15,
        )
        amendment = world.amendment(
            original.id,
            reason="Two terminal loads were keyed twice; gallons corrected downward",
        )
        world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 10000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 10000.00,
                            "date": "2026-08-08",
                        }
                    ],
                }
            ],
            return_id=amendment["id"],
        )

        response = api.file_return(amendment["id"], "A. Amend", world.examiner)

        filed_amendment = validate_success(response, expected_status=200)
        assert cents_for(10000.00, "GASOLINE") == 286000
        assert_return_money(
            filed_amendment,
            tax_due_cents=286000,
            interest_cents=1875,
            penalty_cents=25094,
            total_remittance_cents=312969,
            amendment_delta_cents=-214000,
            days_late=15,
        )
        assert filed_amendment["amendment_sequence"] == 1
        assert filed_amendment["amends_return_id"] == original.id

        superseded = validate_success(api.get_return(original.id, world.examiner))
        assert_return_statuses(superseded, "SUPERSEDED")
        assert superseded["amendment_count"] == 1
        assert_return_money(superseded, interest_cents=1875, penalty_cents=25094)

        entries = world.ledger(filer["id"])
        assert_ledger_sequence(
            entries,
            [
                ("RETURN_TAX", 500000),
                ("INTEREST", 1875),
                ("PENALTY", 25094),
                ("RETURN_TAX_ADJUSTMENT", -214000),
            ],
        )

        licensee = validate_success(api.get_licensee(filer["id"], officer_headers))
        assert licensee["balance_cents"] == 312969
        assert (
            licensee["late_filing_count"] == 1
        ), "amending an already-late period must not count the lateness twice"

    def test_an_amendment_reproducing_the_same_gallons_leaves_the_ytd_total_alone(
        self, api, world, officer_headers
    ):
        """The superseded row leaves the filed set as the amendment joins it, so ytd stays 1000.00.

        PRD: "Because an amendment supersedes its target inside the very same request in which the
        amendment row joins the filed set, an amendment whose schedules reproduce the superseded
        return's gallons leaves `effective_taxable_gallons_ytd` unchanged."
        PRD: "A superseded row immediately drops out of every filed-filtered aggregate in the
        system: the bond basis, `effective_taxable_gallons_ytd`, the cross-match input set, and the
        refund tax-paid pool."

        Design: Corner/calculations/amendment_reproducing_the_same_gallons_leaves_ytd_gallons_unchanged
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Invariant Fuel Supply LLC")
        filer = world.new_licensee("DISTRIBUTOR", legal_name="Invariant Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        schedules = [
            {
                "code": "SCH_2_RECEIVED_TAX_UNPAID",
                "product": "GASOLINE",
                "total": 1000.00,
                "lines": [
                    {
                        "counterparty": supplier["id"],
                        "gallons": 1000.00,
                        "date": "2026-08-04",
                    }
                ],
            }
        ]
        original = world.filed_return(
            filer["id"], "2026-08", schedules, attest_name="I. Invariant"
        )
        assert_return_money(
            original.row, tax_due_cents=28600, interest_cents=0, penalty_cents=0
        )
        amendment = world.amendment(
            original.id, reason="Counterparty name corrected; gallons unchanged"
        )
        world.build_return(
            filer["id"], "2026-08", schedules, return_id=amendment["id"]
        )

        response = api.file_return(amendment["id"], "I. Invariant", world.examiner)

        filed_amendment = validate_success(response, expected_status=200)
        assert_return_money(
            filed_amendment,
            taxable_gallons_total=1000.00,
            tax_due_cents=28600,
            interest_cents=0,
            penalty_cents=0,
            amendment_delta_cents=0,
        )

        licensee = validate_success(api.get_licensee(filer["id"], officer_headers))
        assert_gallons(
            licensee["effective_taxable_gallons_ytd"],
            1000.00,
            "effective_taxable_gallons_ytd after a gallons-neutral amendment",
        )

        entries = world.ledger(filer["id"])
        assert_ledger_sequence(
            entries, [("RETURN_TAX", 28600), ("RETURN_TAX_ADJUSTMENT", 0)]
        )
        assert licensee["balance_cents"] == 28600

        rows, meta = validate_paginated(
            api.list_returns(
                world.examiner,
                params={
                    "licensee_id": filer["id"],
                    "period_month": "2026-08",
                    "filing_status": "FILED",
                },
            )
        )
        assert_total_count(meta, 1, "FILED returns of the amended period")
        assert ids_of(rows) == [amendment["id"]]


class TestAssessmentArithmetic:
    def test_the_evasion_indicator_selects_the_fraud_penalty_rate(
        self, api, world, supervisor_headers, officer_headers
    ):
        """0.50 of 250000 plus four truncated days of interest is 375250, not the negligence figure.

        PRD: "`assessment_penalty_cents` is `additional_tax_cents` multiplied by 0.50 when
        `evasion_indicator` is true and by 0.10 when it is false, rounded half up."
        PRD: "Interest runs from the original statutory due date of the audited span's last period —
        the 20th day of the month following `period_end_month`, at 23:59:59Z — to the logical clock at
        issuance: the elapsed time is divided into whole days and truncated **down**, with a floor of
        zero days if the clock has not yet passed that date, and `assessment_interest_cents` is
        `additional_tax_cents` multiplied by the daily interest rate of 0.00025 and by that number of
        days, rounded half up."
        PRD: "Issuance sets `assessment_status` to `ISSUED` and `assessed_by_user_id` to the acting
        `X-User-ID`, then appends an `ASSESSMENT` ledger entry for the positive
        `assessed_total_cents` naming the case as its source and re-derives the subject's
        `balance_cents`."

        Design: Corner/calculations/assessment_with_evasion_indicator_uses_the_fraud_penalty_percentage
        """
        subject = world.new_licensee("DISTRIBUTOR", legal_name="Fraud Test Distribution Inc")
        case = world.case_at(
            subject["id"],
            "PRELIM_FINDINGS",
            period_start_month="2026-08",
            period_end_month="2026-08",
            selection_method="ROADSIDE_REFERRAL",
        )
        world.set_clock("2026-09-25T00:00:00Z")

        response = api.issue_assessment(
            case["id"],
            {"additional_tax_cents": 250000, "evasion_indicator": True},
            supervisor_headers,
        )

        assessed = validate_success(response, expected_status=200)
        assert_assessment_money(
            assessed,
            additional_tax_cents=250000,
            assessment_penalty_cents=125000,
            assessment_interest_cents=250,
            assessed_total_cents=375250,
        )
        assert_case_dimensions(assessed, "PRELIM_FINDINGS", assessment_status="ISSUED")
        assert assessed["evasion_indicator"] is True
        assert (
            assessed["assessed_by_user_id"] == TAX_SUPERVISOR_ID
        ), "assessed_by_user_id records the acting supervisor"

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                subject["id"], officer_headers, params={"entry_type": "ASSESSMENT"}
            )
        )
        assert_total_count(meta, 1, "ASSESSMENT ledger total_count")
        assert_ledger_row(
            rows[0],
            "ASSESSMENT",
            375250,
            source_entity_type="AuditCase",
            source_entity_id=case["id"],
        )

        licensee = validate_success(api.get_licensee(subject["id"], officer_headers))
        assert licensee["balance_cents"] == 375250
