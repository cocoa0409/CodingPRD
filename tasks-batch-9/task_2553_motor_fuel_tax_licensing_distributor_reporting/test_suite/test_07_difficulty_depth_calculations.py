"""Calculation depth: the two scoring variants, the pinned formulas and the boundary values."""

from test_helpers import (
    AUDIT_SELECTION_THRESHOLD,
    TAX_SUPERVISOR_ID,
    ApiErrorId,
    assert_balance_matches_ledger,
    assert_bond_position,
    assert_cents,
    assert_claim_money,
    assert_gallons,
    assert_imposition,
    assert_ledger_sequence,
    assert_return_money,
    assert_return_statuses,
    cents_for,
    refund_cents_for,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    audit_case_payload,
    decide_payload,
    rack_removal_payload,
)


class TestRackBasisVariants:
    def test_the_position_holders_election_alone_moves_the_deferred_tax(
        self, api, world, officer_headers, examiner_headers
    ):
        """One physical load, two position holders: NET defers 245964 and GROSS defers 247200.

        PRD: "The basis is keyed on the **position holder's** irrevocable `gross_net_election`,
        never on the purchaser's. When the position holder elected `NET`, `basis_used` is recorded
        as `NET` and the basis quantity is the removal's `net_gallons`. When the position holder
        elected `GROSS`, `basis_used` is recorded as `GROSS` and the basis quantity is the
        removal's `gross_gallons`."
        PRD: "The same physical load therefore produces a different tax figure depending on whose
        position it left: for an eight-thousand-gallon billed load of `UNDYED_DIESEL`
        temperature-corrected to 7960.00 gallons, the `GROSS` election taxes 40.00 more gallons
        than the `NET` election, a difference of 1236 cents at the undyed-diesel rate."
        PRD: "Otherwise, if the purchaser's `license_type` is `SUPPLIER` or `DISTRIBUTOR` **and**
        the purchaser's `status` is `ACTIVE`, `imposition_point` is `DEFERRED_TO_PURCHASER` -
        imposition moves to that purchaser's own monthly return."
        PRD: "When `imposition_point` is `DEFERRED_TO_PURCHASER`, `taxable_gallons` is the basis
        quantity, `tax_imposed` is false, `tax_amount_cents` is 0, and `deferred_tax_cents` is the
        basis quantity multiplied by the rate and rounded half up - the tax the purchaser will owe
        on its own return."

        Design: Difficulty/dual_variant_calc/rack_basis_net_vs_gross_diverges_on_deferred_tax
        """
        net_holder = world.active_licensee(
            "SUPPLIER",
            legal_name="Northline Fuel Supply LLC",
            fein="41-1000001",
            gross_net_election="NET",
        )
        gross_holder = world.active_licensee(
            "SUPPLIER",
            legal_name="Bluestem Terminal Partners LP",
            fein="41-1000003",
            gross_net_election="GROSS",
        )
        purchaser = world.active_licensee(
            "DISTRIBUTOR",
            legal_name="Ridgeway Fuel Distribution Inc",
            fein="41-1000002",
            gross_net_election="NET",
        )
        assert_bond_position(purchaser, 1500000, 1500000, 0)
        terminal = world.terminal(name="Saint Paul Park Rack")

        net_row = validate_success(
            api.create_rack_removal(
                rack_removal_payload(
                    terminal["id"],
                    net_holder["id"],
                    purchaser["id"],
                    bill_of_lading_number="BOL-NET-0001",
                ),
                examiner_headers,
            ),
            expected_status=201,
        )
        gross_row = validate_success(
            api.create_rack_removal(
                rack_removal_payload(
                    terminal["id"],
                    gross_holder["id"],
                    purchaser["id"],
                    bill_of_lading_number="BOL-GROSS-0001",
                ),
                examiner_headers,
            ),
            expected_status=201,
        )

        assert_imposition(
            net_row, "NET", "DEFERRED_TO_PURCHASER", 7960.00, False, 0, 245964
        )
        assert_imposition(
            gross_row, "GROSS", "DEFERRED_TO_PURCHASER", 8000.00, False, 0, 247200
        )
        assert_cents(cents_for(7960.00, "UNDYED_DIESEL"), 245964, "the NET basis rate product")
        assert_cents(cents_for(8000.00, "UNDYED_DIESEL"), 247200, "the GROSS basis rate product")
        assert (
            gross_row["deferred_tax_cents"] - net_row["deferred_tax_cents"] == 1236
        ), "the 40.00-gallon basis difference is worth exactly 1236 cents"

        subject = validate_success(api.get_licensee(purchaser["id"], officer_headers))
        assert_cents(subject["balance_cents"], 0, "purchaser balance_cents")
        assert world.ledger(purchaser["id"]) == [], "a deferred removal posts no ledger entry"


class TestRiskScoreVariants:
    def test_three_open_discrepancies_clear_the_threshold_by_magnitude_but_not_by_count(
        self, api, world, officer_headers, manager_headers
    ):
        """The same three 9999.00-gallon findings score 60 by magnitude and 18 by count.

        PRD: "The variance-weighted reading measures **magnitude**: the licensee's
        `unreported_gallons_total` divided by 500 gallons per point, rounded half up to a whole
        number and then capped at 60. The frequency-weighted reading measures **count**: 6 points
        per unit of `open_discrepancy_count`, capped at 60."
        PRD: "Consider a licensee with three open discrepancies of 9999.00 gallons each: the
        magnitude reading gives 29997 divided by 500, which rounds to 60 and caps at 60, clearing
        the selection threshold on its own; the frequency reading gives 3 times 6, or 18 points,
        and the identical licensee is not selectable at all."
        PRD: "Under `RISK_SCORE` the subject's score in the chosen variant must reach 60 points,
        and a subject below the threshold is refused with `ERR_RISK_SCORE_BELOW_THRESHOLD` (HTTP
        422)."
        PRD: "`selection_score` freezes the score of the chosen variant on the case, and is 0 for
        any method other than `RISK_SCORE` - the frozen figure documents why the case was opened
        even after the underlying discrepancies are worked and the live score moves."

        Design: Difficulty/dual_variant_calc/risk_score_variance_vs_frequency_weighted_flips_audit_selectability
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        distributor = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        world.build_return(
            supplier["id"],
            "2026-08",
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": product,
                    "lines": [
                        {
                            "counterparty": distributor["id"],
                            "gallons": 9999.00,
                            "date": date,
                            "transaction_type": "SALE",
                            "bill_of_lading_number": bol,
                        }
                    ],
                }
                for product, date, bol in (
                    ("GASOLINE", "2026-08-10", "BOL-S5-GAS-001"),
                    ("UNDYED_DIESEL", "2026-08-11", "BOL-S5-UND-001"),
                    ("JET_FUEL", "2026-08-12", "BOL-S5-JET-001"),
                )
            ],
            file=True,
        )
        world.build_return(
            distributor["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "BIODIESEL_B100",
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.00,
                            "date": "2026-08-13",
                            "bill_of_lading_number": "BOL-D1-BIO-001",
                        }
                    ],
                }
            ],
            file=True,
        )

        run = world.run_cross_match("2026-08")
        assert run["matched_cells_count"] == 3, "one cell per product the supplier delivered"
        assert run["discrepancy_count"] == 3, "each 9999.00-gallon cell is out of tolerance"
        assert run["escalated_count"] == 0, "9999.00 is below the 10000.00 escalation threshold"
        assert_gallons(
            run["gross_unreported_gallons_total"], 29997.00, "gross_unreported_gallons_total"
        )

        subject = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert subject["open_discrepancy_count"] == 3, "three findings are open work items"
        assert_gallons(subject["unreported_gallons_total"], 29997.00, "unreported_gallons_total")

        profile = validate_success(api.get_risk_profile(distributor["id"], manager_headers))
        assert (
            profile["risk_score_variance_weighted"] == 60
        ), "29997 / 500 rounds to 60 and caps at 60"
        assert (
            profile["risk_score_frequency_weighted"] == 18
        ), "three open findings at 6 points each"
        assert profile["audit_selection_threshold"] == AUDIT_SELECTION_THRESHOLD
        assert profile["late_filing_count"] == 0, "both returns were filed before the deadline"
        assert profile["dyed_violation_count"] == 0

        validate_error(
            api.create_audit_case(
                audit_case_payload(
                    distributor["id"],
                    "2026-08",
                    "2026-08",
                    selection_method="RISK_SCORE",
                    risk_score_variant="FREQUENCY_WEIGHTED",
                ),
                manager_headers,
            ),
            ApiErrorId.RISK_SCORE_BELOW_THRESHOLD,
            expected_status=422,
        )
        case = validate_success(
            api.create_audit_case(
                audit_case_payload(
                    distributor["id"],
                    "2026-08",
                    "2026-08",
                    selection_method="RISK_SCORE",
                    risk_score_variant="VARIANCE_WEIGHTED",
                ),
                manager_headers,
            ),
            expected_status=201,
        )
        assert case["selection_score"] == 60, "the chosen variant's live score is frozen"
        assert case["risk_score_variant"] == "VARIANCE_WEIGHTED"
        assert case["case_status"] == "OPEN"
        assert case["assessment_status"] == "NONE"


class TestImpositionBranchLadder:
    def test_the_six_branch_ladder_is_walked_strictly_in_order(
        self, api, world, officer_headers, examiner_headers
    ):
        """Four loads differing only in product, destination and certificate pin the branch order.

        PRD: "Six branches are tested **strictly in the order below**; the first branch that
        matches decides `imposition_point`, and no later branch may override it."
        PRD: "If `product_code` is `DYED_DIESEL`, `imposition_point` is `NONE_EXEMPT`. Dyed product
        is never taxed at the rack."
        PRD: "Otherwise, if `destination_state` is not `MN`, `imposition_point` is `TERMINAL_RACK`.
        Tax rides at the rack and the purchaser must claim it back later through an `EXPORT` refund
        claim."
        PRD: "Otherwise, if a valid `GOVERNMENT` certificate or a valid `AGRICULTURE` certificate
        was presented, `imposition_point` is `NONE_EXEMPT`."
        PRD: "When `imposition_point` is `NONE_EXEMPT`, `taxable_gallons` is 0.00, `tax_imposed` is
        false, and both `tax_amount_cents` and `deferred_tax_cents` are 0. When `imposition_point`
        is `TERMINAL_RACK`, `taxable_gallons` is the basis quantity, `tax_imposed` is true,
        `tax_amount_cents` is the basis quantity multiplied by the rate and rounded half up to a
        whole cent, and `deferred_tax_cents` is 0."

        Design: Difficulty/combinatorial_formula/rack_imposition_branch_precedence_ladder
        """
        holder = world.active_licensee(
            "SUPPLIER",
            legal_name="Northline Fuel Supply LLC",
            fein="41-1000001",
            gross_net_election="NET",
        )
        distributor = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        fleet = world.active_licensee(
            "RETAILER", legal_name="Dakota County Fleet Services", fein="41-2000001"
        )
        assert_bond_position(fleet, 400000, 400000, 0)
        government_certificate = world.certificate(
            fleet["id"],
            exemption_type="GOVERNMENT",
            document_number="GOV-CERT-2553-A",
            valid_from="2026-01-01",
            valid_to="2026-12-31",
        )
        assert government_certificate["status"] == "ACTIVE"
        terminal = world.terminal(name="Saint Paul Park Rack")

        def removal(**overrides):
            return validate_success(
                api.create_rack_removal(
                    rack_removal_payload(
                        terminal["id"], holder["id"], **overrides
                    ),
                    examiner_headers,
                ),
                expected_status=201,
            )

        dyed = removal(
            purchaser_licensee_id=distributor["id"],
            product_code="DYED_DIESEL",
            destination_state="IA",
            bill_of_lading_number="BOL-ORD-0001",
        )
        out_of_state = removal(
            purchaser_licensee_id=distributor["id"],
            destination_state="IA",
            bill_of_lading_number="BOL-ORD-0002",
        )
        government = removal(
            purchaser_licensee_id=fleet["id"],
            exemption_certificate_id=government_certificate["id"],
            bill_of_lading_number="BOL-ORD-0003",
        )
        deferred = removal(
            purchaser_licensee_id=distributor["id"],
            bill_of_lading_number="BOL-ORD-0004",
        )

        assert_imposition(dyed, "NET", "NONE_EXEMPT", 0.00, False, 0, 0)
        assert_imposition(out_of_state, "NET", "TERMINAL_RACK", 7960.00, True, 245964, 0)
        assert_imposition(government, "NET", "NONE_EXEMPT", 0.00, False, 0, 0)
        assert_imposition(deferred, "NET", "DEFERRED_TO_PURCHASER", 7960.00, False, 0, 245964)

        holder_reread = validate_success(api.get_licensee(holder["id"], officer_headers))
        purchaser_reread = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert_cents(holder_reread["balance_cents"], 0, "position holder balance_cents")
        assert_cents(purchaser_reread["balance_cents"], 0, "purchaser balance_cents")
        assert world.ledger(distributor["id"]) == [], "a rack removal posts no ledger entry"


class TestReturnTaxRoundingOrder:
    def test_two_lines_of_one_hundred_point_zero_one_are_rounded_once_per_product(
        self, api, world, officer_headers, examiner_headers
    ):
        """200.02 gallons taxed once yields 6181 cents, one cent more than per-line rounding.

        PRD: "The floored net is added to `taxable_gallons_total`, and the floored net multiplied by
        that product's cents-per-gallon rate, rounded half up to a whole cent **once for that
        product**, is added to `tax_due_cents`."
        PRD: "The system does not round per line: two `SCH_2_RECEIVED_TAX_UNPAID` lines of
        `UNDYED_DIESEL` at 100.01 gallons each sum to 200.02 gallons and yield 6181 cents, whereas
        rounding each line first would yield 6180 cents and be one cent short."
        PRD: "`total_remittance_cents` is `tax_due_cents` plus `interest_cents` plus
        `penalty_cents`, added as integers after each component has been rounded on its own."
        PRD: "For an **original** return - one whose `amends_return_id` is null - a `RETURN_TAX`
        entry for the full `tax_due_cents` is appended always, even when the tax is zero; an
        `INTEREST` entry for `interest_cents` is appended only when interest is greater than zero;
        and a `PENALTY` entry for `penalty_cents` is appended only when the penalty is greater than
        zero."

        Design: Difficulty/combinatorial_formula/return_tax_due_single_rounding_per_product
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        filer = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        built = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "UNDYED_DIESEL",
                    "total": 200.02,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.01,
                            "date": "2026-08-07",
                            "bill_of_lading_number": "BOL-D2-UND-001",
                        },
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.01,
                            "date": "2026-08-08",
                            "bill_of_lading_number": "BOL-D2-UND-002",
                        },
                    ],
                }
            ],
            file=True,
        )

        assert_return_statuses(built.row, "FILED", "NOT_MATCHED")
        assert_return_money(built.row, 200.02, 6181, 0, 0, 6181, 0)
        assert cents_for(200.02, "UNDYED_DIESEL") == 6181, "the single rounding gives 6181"
        assert (
            cents_for(100.01, "UNDYED_DIESEL") * 2 == 6180
        ), "rounding each line first would be one cent short"

        schedule = validate_success(api.get_schedule(built.schedule["id"], examiner_headers))
        assert_gallons(schedule["total_gallons"], 200.02, "declared total_gallons")
        assert schedule["line_count"] == 2, "line_count is the one figure the system maintains"

        licensee = validate_success(api.get_licensee(filer["id"], officer_headers))
        assert licensee["late_filing_count"] == 0, "the return was filed before its due instant"
        entries = world.ledger(filer["id"])
        assert_ledger_sequence(entries, [("RETURN_TAX", 6181)])
        assert_balance_matches_ledger(licensee, entries)
        assert_cents(licensee["balance_cents"], 6181, "balance_cents")


class TestLateFilingChargeOrder:
    def test_interest_then_the_tier_then_the_statutory_floor(
        self, api, world, officer_headers
    ):
        """Interest on tax alone, the tier on tax plus interest, then the 5000-cent floor wins.

        PRD: "`days_late` is 0 when `filed_at` is at or before `due_at`; otherwise it is the elapsed
        time from `due_at` to `filed_at` divided into whole days and rounded **up** to the next
        whole day, so any part of a day counts as a full day."
        PRD: "Otherwise it is `tax_due_cents` multiplied by a daily interest rate of 0.00025 and by
        `days_late`, rounded half up to a whole cent. Interest accrues on tax only, never on
        penalty."
        PRD: "Otherwise the system forms a subtotal of `tax_due_cents` plus `interest_cents`, and
        selects a percentage by lateness tier: 5 percent when `days_late` is 30 or fewer, 10 percent
        when `days_late` is 60 or fewer, and 15 percent beyond 60 days."
        PRD: "The penalty is then the greater of a statutory floor of 5000 cents and the subtotal
        multiplied by that percentage rounded half up to a whole cent."
        PRD: "When `days_late` is 1 or more **and** the return is an original, `late_filing_count`
        increases by one; a period is counted late exactly once, on its original filing, so amending
        an already-late period does not count it again."

        Design: Difficulty/combinatorial_formula/late_filing_interest_then_penalty_tier_then_floor
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        filer = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        built = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "UNDYED_DIESEL",
                    "total": 200.02,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.01,
                            "date": "2026-08-07",
                            "bill_of_lading_number": "BOL-D2-UND-001",
                        },
                        {
                            "counterparty": supplier["id"],
                            "gallons": 100.01,
                            "date": "2026-08-08",
                            "bill_of_lading_number": "BOL-D2-UND-002",
                        },
                    ],
                }
            ],
        )
        world.set_clock("2026-10-05T00:00:00Z")

        filed = world.file_return(built.id, "D. Ridgeway")
        assert_return_statuses(filed, "FILED", "NOT_MATCHED")
        assert_return_money(filed, 200.02, 6181, 23, 5000, 11204, 15)
        assert 6181 + 23 == 6204, "the tier is keyed on the tax-plus-interest subtotal"
        assert round(6204 * 0.05) == 310, "5 percent of the subtotal is only 310 cents"

        licensee = validate_success(api.get_licensee(filer["id"], officer_headers))
        assert licensee["late_filing_count"] == 1, "one late original filing"
        entries = world.ledger(filer["id"])
        assert_ledger_sequence(
            entries, [("RETURN_TAX", 6181), ("INTEREST", 23), ("PENALTY", 5000)]
        )
        assert_balance_matches_ledger(licensee, entries)
        assert_cents(licensee["balance_cents"], 11204, "balance_cents")


class TestCrossMatchToleranceBoundary:
    def test_a_variance_of_exactly_five_gallons_creates_nothing_and_five_point_zero_one_creates_one(
        self, api, world, officer_headers, examiner_headers
    ):
        """The tolerance comparison is strict, so the boundary value itself is the passing case.

        PRD: "A discrepancy is created only when the absolute value of `variance_gallons` is
        **strictly greater** than the run's `tolerance_gallons`. A variance of exactly 5.00 gallons
        against the default tolerance creates nothing at all - it increments `matched_cells_count`
        and is otherwise forgotten."
        PRD: "Every cell examined increments `matched_cells_count`, whether or not it produces a
        finding."
        PRD: "Once the cells are enumerated, every filed return of the period is stamped: a return
        whose licensee appears in no discrepancy this run created moves to `MATCH_CLEAN`, and every
        other filed return of the period moves to `MATCH_VARIANCE`."
        PRD: "Each created discrepancy increments the purchaser's `open_discrepancy_count` and, when
        the direction is `UNREPORTED_BY_PURCHASER`, adds the variance to the purchaser's own
        `unreported_gallons_total`."

        Design: Difficulty/boundary_precision_check/cross_match_tolerance_exact_five_gallons_creates_nothing
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        distributor = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )

        def sold(period_month, gallons, date, bol):
            return world.build_return(
                supplier["id"],
                period_month,
                [
                    {
                        "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                        "product": "UNDYED_DIESEL",
                        "lines": [
                            {
                                "counterparty": distributor["id"],
                                "gallons": gallons,
                                "date": date,
                                "transaction_type": "SALE",
                                "bill_of_lading_number": bol,
                            }
                        ],
                    }
                ],
                file=True,
            )

        def received(period_month, gallons, date, bol):
            return world.build_return(
                distributor["id"],
                period_month,
                [
                    {
                        "code": "SCH_1_RECEIVED_TAX_PAID",
                        "product": "UNDYED_DIESEL",
                        "lines": [
                            {
                                "counterparty": supplier["id"],
                                "gallons": gallons,
                                "date": date,
                                "bill_of_lading_number": bol,
                            }
                        ],
                    }
                ],
                file=True,
            )

        world.set_clock("2026-09-05T00:00:00Z")
        august_sold = sold("2026-08", 10005.00, "2026-08-10", "BOL-AUG-S5-001")
        august_received = received("2026-08", 10000.00, "2026-08-11", "BOL-AUG-D1-001")
        world.set_clock("2026-10-05T00:00:00Z")
        september_sold = sold("2026-09", 10005.01, "2026-09-10", "BOL-SEP-S5-001")
        september_received = received("2026-09", 10000.00, "2026-09-11", "BOL-SEP-D1-001")

        august_run = world.run_cross_match("2026-08")
        september_run = world.run_cross_match("2026-09")

        assert_gallons(august_run["tolerance_gallons"], 5.00, "snapshotted tolerance_gallons")
        assert august_run["matched_cells_count"] == 1, "the cell was examined"
        assert august_run["discrepancy_count"] == 0, "5.00 is not strictly greater than 5.00"
        assert_gallons(
            august_run["gross_unreported_gallons_total"],
            0.00,
            "gross_unreported_gallons_total",
        )
        assert world.discrepancies(run_id=august_run["id"]) == []
        for return_id in (august_sold.id, august_received.id):
            reread = validate_success(api.get_return(return_id, examiner_headers))
            assert_return_statuses(reread, "FILED", "MATCH_CLEAN")

        assert september_run["matched_cells_count"] == 1
        assert september_run["discrepancy_count"] == 1, "5.01 clears the tolerance"
        assert september_run["escalated_count"] == 0
        finding = world.only_discrepancy(september_run["id"])
        assert_gallons(finding["supplier_gallons"], 10005.01, "supplier_gallons")
        assert_gallons(finding["distributor_gallons"], 10000.00, "distributor_gallons")
        assert_gallons(finding["variance_gallons"], 5.01, "variance_gallons")
        assert finding["direction"] == "UNREPORTED_BY_PURCHASER"
        assert finding["status"] == "OPEN"
        for return_id in (september_sold.id, september_received.id):
            reread = validate_success(api.get_return(return_id, examiner_headers))
            assert_return_statuses(reread, "FILED", "MATCH_VARIANCE")

        purchaser = validate_success(api.get_licensee(distributor["id"], officer_headers))
        assert purchaser["open_discrepancy_count"] == 1
        assert_gallons(purchaser["unreported_gallons_total"], 5.01, "unreported_gallons_total")


class TestRefundPayabilityFloor:
    def test_two_thousand_cents_is_payable_and_one_thousand_nine_hundred_and_ninety_nine_is_not(
        self, api, world, officer_headers, examiner_headers, supervisor_headers
    ):
        """64.72 gallons round to exactly the inclusive floor; 64.69 gallons fall one cent short.

        PRD: "`refund_amount_cents` is `allowable_gallons` multiplied by 30.9 cents per gallon,
        rounded half up to a whole cent, exactly once."
        PRD: "`APPROVED` leaves `allowable_gallons` and `refund_amount_cents` at their submit-time
        values and moves `status` to `APPROVED`. It is permitted only when `refund_amount_cents`
        reaches the 2000-cent payability floor, inclusive; below it the decision is refused with
        `ERR_REFUND_BELOW_MINIMUM` (HTTP 422)."
        PRD: "All three branches stamp `decider_user_id` with the acting `X-User-ID`."

        Design: Difficulty/boundary_precision_check/refund_minimum_payable_amount_inclusive_at_two_thousand_cents
        """
        supplier = world.active_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        claimant = world.active_licensee(
            "DISTRIBUTOR", legal_name="Ridgeway Fuel Distribution Inc", fein="41-1000002"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        world.tax_paid_pool(claimant["id"], "2026-08", 2000.00, counterparty_id=supplier["id"])

        at_floor = world.refund_claim(claimant["id"], "2026-08", 64.72)
        below_floor = world.refund_claim(claimant["id"], "2026-08", 64.69)
        assert_claim_money(at_floor, 64.72, 2000)
        assert_claim_money(below_floor, 64.69, 1999)
        assert refund_cents_for(64.72) == 2000, "64.72 gallons at 30.9 cents rounds to 2000"
        assert refund_cents_for(64.69) == 1999, "64.69 gallons at 30.9 cents rounds to 1999"
        world.review_claim(at_floor["id"], "APPROVE", as_headers=examiner_headers)
        world.review_claim(below_floor["id"], "APPROVE", as_headers=examiner_headers)

        approved = validate_success(
            api.decide_claim(at_floor["id"], decide_payload("APPROVED"), supervisor_headers)
        )
        assert approved["status"] == "APPROVED", "the floor is inclusive at exactly 2000 cents"
        assert approved["decider_user_id"] == TAX_SUPERVISOR_ID
        assert_claim_money(approved, 64.72, 2000)

        validate_error(
            api.decide_claim(below_floor["id"], decide_payload("APPROVED"), supervisor_headers),
            ApiErrorId.REFUND_BELOW_MINIMUM,
            expected_status=422,
        )
        refused = validate_success(api.get_refund_claim(below_floor["id"], examiner_headers))
        assert refused["status"] == "REVIEWED", "nothing at all is written on the refusal"
        assert refused["decider_user_id"] is None
        assert_claim_money(refused, 64.69, 1999)

        licensee = validate_success(api.get_licensee(claimant["id"], officer_headers))
        assert_cents(licensee["balance_cents"], 0, "balance_cents")
        assert world.ledger(claimant["id"], entry_type="REFUND") == [], "neither claim was paid"


class TestBondBasisEmptySetAndClamp:
    def test_an_empty_basis_assumes_liability_and_a_zero_tax_return_falls_to_the_minimum(
        self, api, world, officer_headers, examiner_headers
    ):
        """No filed returns assumes 500000 cents; one zero-tax return clamps the requirement to 200000.

        PRD: "When that set is empty, `avg_monthly_tax_liability_cents` is the assumed liability for
        a brand-new licensee, 500000 cents."
        PRD: "The product is rounded **up** to the next whole multiple of 100000 cents, and only
        then clamped into the statutory band: `required_bond_cents` is the clamped value, never below
        200000 cents and never above 100000000 cents."
        PRD: "A dedicated computed read exposes `avg_monthly_tax_liability_cents`,
        `required_bond_cents`, `posted_bond_cents`, `bond_deficiency_cents` and
        `basis_return_count`, the last being how many filed returns actually entered the average
        (0, 1, 2 or 3)."
        PRD: "Then the reconciliation: for every schedule of the return, the declared
        `total_gallons` must equal the exact two-decimal sum of that schedule's line `gallons`, and
        its `line_count` must equal the number of those lines; a mismatch is refused with
        `ERR_SCHEDULE_TOTALS_MISMATCH` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/bond_requirement_on_empty_basis_set_then_min_bond_clamp
        """
        supplier = world.new_licensee(
            "SUPPLIER", legal_name="Northline Fuel Supply LLC", fein="41-1000001"
        )
        assert supplier["status"] == "PENDING_BOND"
        world.set_clock("2026-09-05T00:00:00Z")

        empty_basis = validate_success(api.get_bond_status(supplier["id"], officer_headers))
        assert_bond_position(empty_basis, 1500000, 0, 1500000, 500000, 0)

        world.post_bond(supplier["id"], 1500000)
        activated = world.activate(supplier["id"])
        assert activated["status"] == "ACTIVE"

        built = world.build_return(
            supplier["id"],
            "2026-08",
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": "GASOLINE",
                    "total": 0.00,
                    "lines": [],
                }
            ],
            file=True,
        )
        assert_return_statuses(built.row, "FILED", "NOT_MATCHED")
        assert_return_money(built.row, 0.00, 0, 0, 0, 0, 0)
        schedule = validate_success(api.get_schedule(built.schedule["id"], examiner_headers))
        assert_gallons(schedule["total_gallons"], 0.00, "declared total_gallons")
        assert schedule["line_count"] == 0, "both sides of the reconciliation are 0.00"

        clamped = validate_success(api.get_bond_status(supplier["id"], officer_headers))
        assert_bond_position(clamped, 200000, 1500000, 0, 0, 1)

        licensee = validate_success(api.get_licensee(supplier["id"], officer_headers))
        assert licensee["status"] == "ACTIVE"
        assert_cents(licensee["balance_cents"], 0, "balance_cents")
        entries = world.ledger(supplier["id"])
        assert_ledger_sequence(entries, [("RETURN_TAX", 0)])
        assert_balance_matches_ledger(licensee, entries)
