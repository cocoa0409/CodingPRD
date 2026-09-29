"""Validation refusals: certificate bands, aggregate reconciliation and fiscal gates."""

from test_helpers import (
    RETURNS_EXAMINER_ID,
    TAX_SUPERVISOR_ID,
    ApiErrorId,
    assert_bond_position,
    assert_claim_money,
    assert_gallons,
    assert_imposition,
    assert_ledger_row,
    assert_return_money,
    assert_return_statuses,
    assert_total_count,
    make_tax_supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    licensee_payload,
    line_payload,
    payment_payload,
    rack_removal_payload,
    refund_claim_payload,
    resolve_payload,
)


class TestCertificateBands:
    def test_an_agriculture_certificate_cannot_cover_a_gasoline_exempt_line(self, api, world):
        """AGRICULTURE covers UNDYED_DIESEL only, so a flawless certificate still fails on GASOLINE.

        PRD: "Those product sets are fixed: `GOVERNMENT` covers `GASOLINE` and `UNDYED_DIESEL`;
        `AGRICULTURE` covers `UNDYED_DIESEL` only; `EXPORT` covers `GASOLINE`, `UNDYED_DIESEL`,
        `JET_FUEL`, `AVIATION_GAS`, `ETHANOL_E100` and `BIODIESEL_B100`."
        PRD: "Third, the line's product must be covered by that certificate's exemption type, or the
        line is refused with `ERR_EXEMPTION_PRODUCT_MISMATCH`."

        Design: Corner/validations/agriculture_certificate_on_a_gasoline_exempt_line_returns_exemption_product_mismatch
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Prairie Fuel Supply LLC")
        farm = world.new_licensee(
            "RETAILER", legal_name="Prairie Farm Fuels LLC", retail_channel="FARM"
        )
        certificate = world.certificate(
            farm["id"],
            exemption_type="AGRICULTURE",
            document_number="AG-5300-001",
            valid_from="2026-08-01",
            valid_to="2026-08-31",
        )
        world.set_clock("2026-09-05T00:00:00Z")
        draft = world.draft_return(supplier["id"], "2026-08")
        gasoline_schedule = world.schedule(
            draft["id"], "SCH_6_EXEMPT_SALES", "GASOLINE", 400.00
        )

        response = api.create_line(
            gasoline_schedule["id"],
            line_payload(
                farm["id"],
                400.00,
                "2026-08-14",
                transaction_type="SALE",
                exemption_certificate_id=certificate["id"],
            ),
            world.examiner,
        )

        validate_error(response, ApiErrorId.EXEMPTION_PRODUCT_MISMATCH, expected_status=422)
        reread = validate_success(api.get_schedule(gasoline_schedule["id"], world.examiner))
        assert reread["line_count"] == 0, "a refused line must not be counted"
        _rows, meta = validate_paginated(
            api.list_schedule_lines(
                world.examiner, params={"schedule_id": gasoline_schedule["id"]}
            )
        )
        assert_total_count(meta, 0, "lines under the GASOLINE exempt schedule")

        diesel_schedule = world.schedule(
            draft["id"], "SCH_6_EXEMPT_SALES", "UNDYED_DIESEL", 400.00
        )
        accepted = validate_success(
            api.create_line(
                diesel_schedule["id"],
                line_payload(
                    farm["id"],
                    400.00,
                    "2026-08-14",
                    transaction_type="SALE",
                    exemption_certificate_id=certificate["id"],
                ),
                world.examiner,
            ),
            expected_status=201,
        )
        assert accepted["exemption_certificate_id"] == certificate["id"]

    def test_the_holder_check_answers_before_the_product_check_on_one_line(self, api, world):
        """One line breaks both rules, and the earlier holder rule is the one that speaks.

        PRD: "First, a presented certificate must belong to the line's counterparty, or the line is
        refused with `ERR_CERTIFICATE_HOLDER_MISMATCH`."
        PRD: "Third, the line's product must be covered by that certificate's exemption type, or the
        line is refused with `ERR_EXEMPTION_PRODUCT_MISMATCH`."

        Design: Corner/validations/certificate_holder_mismatch_outranks_product_mismatch_on_one_line
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Two Farms Fuel Supply LLC")
        farm_a = world.new_licensee(
            "RETAILER", legal_name="Farm A Fuels LLC", retail_channel="FARM"
        )
        farm_b = world.new_licensee(
            "RETAILER", legal_name="Farm B Fuels LLC", retail_channel="FARM"
        )
        certificate_b = world.certificate(
            farm_b["id"],
            exemption_type="AGRICULTURE",
            document_number="AG-5400-002",
            valid_from="2026-08-01",
            valid_to="2026-08-31",
        )
        world.set_clock("2026-09-05T00:00:00Z")
        draft = world.draft_return(supplier["id"], "2026-08")
        schedule = world.schedule(draft["id"], "SCH_6_EXEMPT_SALES", "GASOLINE", 300.00)

        response = api.create_line(
            schedule["id"],
            line_payload(
                farm_a["id"],
                300.00,
                "2026-08-14",
                transaction_type="SALE",
                exemption_certificate_id=certificate_b["id"],
            ),
            world.examiner,
        )

        validate_error(response, ApiErrorId.CERTIFICATE_HOLDER_MISMATCH, expected_status=422)

        masked = api.create_line(
            schedule["id"],
            line_payload(
                farm_b["id"],
                300.00,
                "2026-08-14",
                transaction_type="SALE",
                exemption_certificate_id=certificate_b["id"],
            ),
            world.examiner,
        )
        validate_error(masked, ApiErrorId.EXEMPTION_PRODUCT_MISMATCH, expected_status=422)

    def test_an_export_line_may_not_name_a_home_state_counterparty(self, api, world):
        """On SCH_7_EXPORTS the counterparty test is on mailing_state, not on license_type.

        PRD: "Lines on `SCH_7_EXPORTS` require a counterparty whose `mailing_state` is something
        other than the home state `MN`."
        PRD: "A violation of either rule is refused with `ERR_COUNTERPARTY_TYPE_INVALID` (HTTP 422)."

        Design: Corner/validations/export_line_to_a_home_state_counterparty_returns_counterparty_type_invalid
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Border Fuel Supply LLC")
        inside = world.new_licensee(
            "DISTRIBUTOR", legal_name="Border Inside Distribution Inc", mailing_state="MN"
        )
        outside = world.new_licensee(
            "DISTRIBUTOR", legal_name="Border Outside Distribution Inc", mailing_state="WI"
        )
        inside_certificate = world.certificate(
            inside["id"],
            exemption_type="EXPORT",
            document_number="EX-6100-002",
            valid_from="2026-08-01",
            valid_to="2026-08-31",
        )
        outside_certificate = world.certificate(
            outside["id"],
            exemption_type="EXPORT",
            document_number="EX-6100-003",
            valid_from="2026-08-01",
            valid_to="2026-08-31",
        )
        world.set_clock("2026-09-05T00:00:00Z")
        draft = world.draft_return(supplier["id"], "2026-08")
        schedule = world.schedule(draft["id"], "SCH_7_EXPORTS", "GASOLINE", 5000.00)

        response = api.create_line(
            schedule["id"],
            line_payload(
                inside["id"],
                5000.00,
                "2026-08-18",
                transaction_type="EXPORT",
                exemption_certificate_id=inside_certificate["id"],
            ),
            world.examiner,
        )

        validate_error(response, ApiErrorId.COUNTERPARTY_TYPE_INVALID, expected_status=422)

        validate_success(
            api.create_line(
                schedule["id"],
                line_payload(
                    outside["id"],
                    5000.00,
                    "2026-08-18",
                    transaction_type="EXPORT",
                    exemption_certificate_id=outside_certificate["id"],
                ),
                world.examiner,
            ),
            expected_status=201,
        )
        reread = validate_success(api.get_schedule(schedule["id"], world.examiner))
        assert reread["line_count"] == 1, "only the out-of-state line landed"

        _rows, meta = validate_paginated(
            api.list_schedule_lines(
                world.examiner,
                params={"exemption_certificate_id": inside_certificate["id"]},
            )
        )
        assert_total_count(meta, 0, "lines under the refused MN certificate")

    def test_a_dyed_sale_is_refused_for_a_highway_retailer_and_accepted_for_a_farm_retailer(
        self, api, world, officer_headers
    ):
        """The counterparty's retail_channel alone decides the identical dyed-sales line.

        PRD: "Fourth come the dyed-fuel prohibitions: a line on a `SCH_10_DYED_SALES` schedule may
        not name a counterparty whose `retail_channel` is `HIGHWAY`, and a `DYED_DIESEL` line may
        never appear on a `SCH_2_RECEIVED_TAX_UNPAID`, `SCH_5_DELIVERED_TAX_COLLECTED` or
        `SCH_6_EXEMPT_SALES` schedule; either violation is refused with
        `ERR_DYED_FUEL_ON_ROAD_PROHIBITED` (HTTP 422)."
        PRD: "`retail_channel` records the channel a retailer serves, one of `HIGHWAY`, `MARINE`,
        `FARM` or `NOT_APPLICABLE`, defaulting to `NOT_APPLICABLE`; it is the conditional flag behind
        the dyed-fuel-on-road prohibition, which the system enforces on dyed-sales schedule lines
        rather than at registration."

        Design: Corner/validations/dyed_sale_to_a_highway_retailer_is_refused_and_to_a_farm_retailer_passes
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Dyed Channel Fuel Supply LLC")
        highway = world.new_licensee(
            "RETAILER", legal_name="Dyed Channel Highway Stops LLC", retail_channel="HIGHWAY"
        )
        farm = world.new_licensee(
            "RETAILER", legal_name="Dyed Channel Farm Depot LLC", retail_channel="FARM"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        draft = world.draft_return(supplier["id"], "2026-08")
        schedule = world.schedule(draft["id"], "SCH_10_DYED_SALES", "DYED_DIESEL", 2000.00)

        response = api.create_line(
            schedule["id"],
            line_payload(
                highway["id"], 1000.00, "2026-08-12", transaction_type="SALE"
            ),
            world.examiner,
        )

        validate_error(response, ApiErrorId.DYED_FUEL_ON_ROAD_PROHIBITED, expected_status=422)

        validate_success(
            api.create_line(
                schedule["id"],
                line_payload(farm["id"], 1000.00, "2026-08-12", transaction_type="SALE"),
                world.examiner,
            ),
            expected_status=201,
        )
        reread = validate_success(api.get_schedule(schedule["id"], world.examiner))
        assert reread["line_count"] == 1, "only the FARM line landed"

        refused_counterparty = validate_success(
            api.get_licensee(highway["id"], officer_headers)
        )
        assert (
            refused_counterparty["dyed_violation_count"] == 0
        ), "a refused schedule line is not a roadside dyed-fuel violation"


class TestFiscalGates:
    def test_a_payment_of_exactly_the_balance_lands_and_one_more_cent_does_not(
        self, api, world, supervisor_headers, officer_headers
    ):
        """The comparison forbids only an excess, so the exact balance clears it to zero.

        PRD: "The amount must be greater than zero and must not exceed the licensee's current
        `balance_cents`, since no credit balances are created through payments; a violation is refused
        with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422)."
        PRD: "The request appends a `PAYMENT` ledger entry for the **negative** of the submitted
        `amount_cents` — the submitted figure is a positive remittance, the posted figure is a
        negative charge — with `source_entity_type` `Payment`, re-derives `balance_cents`, and
        increments the licensee's `version`."

        Design: Corner/validations/payment_of_exactly_the_balance_is_accepted_and_one_cent_more_is_not
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Exact Pay Fuel Supply LLC")
        payer = world.new_licensee("DISTRIBUTOR", legal_name="Exact Pay Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        world.filed_return(
            payer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "GASOLINE",
                    "total": 1000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 1000.00,
                            "date": "2026-08-06",
                        }
                    ],
                }
            ],
            attest_name="E. Exact",
        )

        response = api.create_payment(
            payer["id"],
            payment_payload(
                28600,
                effective_date="2026-09-05",
                memo="ACH settlement of the 2026-08 period",
            ),
            supervisor_headers,
        )

        entry = validate_success(response, expected_status=201)
        assert_ledger_row(entry, "PAYMENT", -28600, source_entity_type="Payment")

        settled = validate_success(api.get_licensee(payer["id"], officer_headers))
        assert settled["balance_cents"] == 0

        rows, meta = validate_paginated(api.list_ledger_entries(payer["id"], officer_headers))
        assert_total_count(meta, 2, "ledger rows after the exact settlement")
        assert sum(row["amount_cents"] for row in rows) == 0

        overpayment = api.create_payment(
            payer["id"],
            payment_payload(1, effective_date="2026-09-05"),
            supervisor_headers,
        )
        validate_error(overpayment, ApiErrorId.PAYMENT_EXCEEDS_BALANCE, expected_status=422)
        _rows, after_meta = validate_paginated(
            api.list_ledger_entries(payer["id"], officer_headers)
        )
        assert_total_count(after_meta, 2, "ledger rows after the refused overpayment")

    def test_a_rack_removal_is_refused_while_the_purchaser_carries_a_bond_deficiency(
        self, api, world, officer_headers
    ):
        """The fiscal rule needs the derived deficiency, and posting a bond flips the same request.

        PRD: "When a removal has the shape that would defer tax — the purchaser's `license_type` is
        `SUPPLIER` or `DISTRIBUTOR`, the `destination_state` equals the home state `MN`, and no valid
        exemption certificate has been presented — the removal is refused if that purchaser's
        `bond_deficiency_cents` is greater than zero, whatever the purchaser's `status` happens to be."
        PRD: "That refusal carries `ERR_PURCHASER_BOND_DEFICIENT` (HTTP 422)."

        Design: Corner/validations/bond_deficiency_is_derived_before_the_deferral_shape_refusal
        """
        holder = world.active_licensee(
            "SUPPLIER",
            bond_cents=1500000,
            legal_name="Cascade Fuel Supply LLC",
            gross_net_election="NET",
        )
        # A SUSPENDED distributor: the rack's purchaser-status check ("must be
        # ACTIVE or SUSPENDED") is passed, and the suspension multiplier of 2.0
        # doubles the requirement above the posted bond, so the fiscal check is
        # reached with a standing deficiency -- "whatever the purchaser's
        # `status` happens to be".
        purchaser = world.suspended_licensee(
            "DISTRIBUTOR",
            legal_name="Cascade Distribution Inc",
            gross_net_election="NET",
        )
        terminal = world.terminal(name="Cascade River Terminal", state_code="MN")
        payload = rack_removal_payload(
            terminal["id"],
            holder["id"],
            purchaser["id"],
            product_code="GASOLINE",
            gross_gallons=8000.00,
            net_gallons=7960.00,
            removal_date="2026-07-28",
            destination_state="MN",
        )

        response = api.create_rack_removal(payload, world.examiner)

        validate_error(response, ApiErrorId.PURCHASER_BOND_DEFICIENT, expected_status=422)
        status = validate_success(api.get_bond_status(purchaser["id"], officer_headers))
        assert_bond_position(
            status,
            required_bond_cents=3000000,
            posted_bond_cents=1500000,
            bond_deficiency_cents=1500000,
        )

        world.post_bond(purchaser["id"], 3000000)
        accepted = validate_success(
            api.create_rack_removal(payload, world.examiner), expected_status=201
        )
        assert_imposition(
            accepted,
            basis_used="NET",
            imposition_point="TERMINAL_RACK",
            taxable_gallons=7960.00,
            tax_imposed=True,
            tax_amount_cents=227656,
            deferred_tax_cents=0,
        )

        _rows, meta = validate_paginated(
            api.list_rack_removals(
                world.examiner, params={"purchaser_licensee_id": purchaser["id"]}
            )
        )
        assert_total_count(meta, 1, "rack removals after the refusal and the retry")


class TestPeriodAndAggregateGates:
    def test_a_cross_match_run_for_the_clock_s_own_month_is_refused(self, api, world):
        """The gate compares months, so standing in 2026-09 only 2026-08 and earlier are matchable.

        PRD: "The period must be closed, meaning `period_month` is strictly earlier than the logical
        clock's own month; an in-flight period is not matchable and the attempt fails with
        `ERR_PERIOD_NOT_CLOSED` (HTTP 422)."

        Design: Corner/validations/cross_match_run_for_the_clock_s_own_month_returns_period_not_closed
        """
        world.set_clock("2026-09-05T00:00:00Z")

        response = api.create_cross_match_run({"period_month": "2026-09"}, world.examiner)

        validate_error(response, ApiErrorId.PERIOD_NOT_CLOSED, expected_status=422)
        _rows, meta = validate_paginated(
            api.list_cross_match_runs(world.examiner, params={"period_month": "2026-09"})
        )
        assert_total_count(meta, 0, "runs for the in-flight period")

        accepted = validate_success(
            api.create_cross_match_run({"period_month": "2026-08"}, world.examiner),
            expected_status=201,
        )
        assert accepted["run_status"] == "COMPLETED"
        assert accepted["matched_cells_count"] == 0
        assert accepted["discrepancy_count"] == 0

    def test_a_refund_claim_needs_a_filed_period_before_the_pool_is_even_measured(
        self, api, world, examiner_headers
    ):
        """The 2026-08 return sits in DRAFT, so the claim is refused for the period, not for the pool.

        PRD: "The claimant must already have a filed, non-superseded return for `period_month`,
        because that return is the only source of the tax-paid pool; without one the claim fails with
        `ERR_REFUND_PERIOD_NOT_FILED` (HTTP 422)."

        Design: Corner/validations/refund_claim_against_a_draft_period_returns_refund_period_not_filed
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Draft Period Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Draft Period Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        built = world.build_return(
            claimant["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "UNDYED_DIESEL",
                    "total": 200.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 200.00,
                            "date": "2026-08-09",
                        }
                    ],
                }
            ],
        )

        response = api.create_refund_claim(
            refund_claim_payload(claimant["id"], "2026-08", 100.00), examiner_headers
        )

        validate_error(response, ApiErrorId.REFUND_PERIOD_NOT_FILED, expected_status=422)
        _rows, meta = validate_paginated(
            api.list_refund_claims(examiner_headers, params={"licensee_id": claimant["id"]})
        )
        assert_total_count(meta, 0, "claims after the refused filing")

        world.file_return(built.id, "D. Draftperiod")
        accepted = validate_success(
            api.create_refund_claim(
                refund_claim_payload(claimant["id"], "2026-08", 100.00), examiner_headers
            ),
            expected_status=201,
        )
        assert_claim_money(accepted, 100.00, 3090)

    def test_a_declared_total_that_misses_a_line_blocks_filing_as_an_equality(
        self, api, world, officer_headers
    ):
        """Every line is legal alone; the offence is the aggregate, and it is an equality not a ceiling.

        PRD: "Then the reconciliation: for every schedule of the return, the declared `total_gallons`
        must equal the exact two-decimal sum of that schedule's line `gallons`, and its `line_count`
        must equal the number of those lines; a mismatch is refused with
        `ERR_SCHEDULE_TOTALS_MISMATCH` (HTTP 422)."
        PRD: "as do `attest_name` and `filed_at`, both null while the return is a draft."

        Design: Corner/validations/declared_schedule_total_that_misses_a_line_returns_schedule_totals_mismatch
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Attest Fuel Supply LLC")
        filer = world.new_licensee("DISTRIBUTOR", legal_name="Attest Distribution Inc")
        world.set_clock("2026-09-05T00:00:00Z")
        built = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "UNDYED_DIESEL",
                    "total": 1000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 400.00,
                            "date": "2026-08-04",
                        },
                        {
                            "counterparty": supplier["id"],
                            "gallons": 550.00,
                            "date": "2026-08-19",
                        },
                    ],
                }
            ],
        )

        response = api.file_return(built.id, "A. Attester", world.examiner)

        validate_error(response, ApiErrorId.SCHEDULE_TOTALS_MISMATCH, expected_status=422)
        schedule = validate_success(api.get_schedule(built.schedule["id"], world.examiner))
        assert_gallons(schedule["total_gallons"], 1000.00, "declared total_gallons")
        assert schedule["line_count"] == 2, "the declared total was never quietly repaired"
        still_draft = validate_success(api.get_return(built.id, world.examiner))
        assert_return_statuses(still_draft, "DRAFT", "NOT_MATCHED")
        assert still_draft["filed_at"] is None
        assert still_draft["attest_name"] is None
        _rows, meta = validate_paginated(api.list_ledger_entries(filer["id"], officer_headers))
        assert_total_count(meta, 0, "ledger rows after a refused filing")

        world.line(built.schedule["id"], supplier["id"], 50.00, "2026-08-21")
        filed = validate_success(
            api.file_return(built.id, "A. Attester", world.examiner), expected_status=200
        )
        assert_return_money(filed, taxable_gallons_total=1000.00, tax_due_cents=30900)

        sibling = world.build_return(
            filer["id"],
            "2026-07",
            [
                {
                    "code": "SCH_2_RECEIVED_TAX_UNPAID",
                    "product": "UNDYED_DIESEL",
                    "total": 1000.01,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 1000.00,
                            "date": "2026-07-14",
                        }
                    ],
                }
            ],
        )
        over_declared = api.file_return(sibling.id, "A. Attester", world.examiner)
        validate_error(over_declared, ApiErrorId.SCHEDULE_TOTALS_MISMATCH, expected_status=422)

    def test_a_supplier_return_must_carry_a_delivery_schedule_and_an_empty_return_is_refused(
        self, api, world
    ):
        """Both limbs of the same rule bite: no SCH_5 for a supplier, and no schedules at all.

        PRD: "Finally, a return may not be filed with zero schedules at all, and a return whose filer
        is a `SUPPLIER` must carry at least one `SCH_5_DELIVERED_TAX_COLLECTED` schedule; either
        omission is refused with `ERR_MISSING_REQUIRED_SCHEDULE` (HTTP 422)."

        Design: Corner/validations/supplier_return_without_a_delivery_schedule_returns_missing_required_schedule
        """
        filer = world.new_licensee("SUPPLIER", legal_name="No Sch Five Fuel Supply LLC")
        upstream = world.new_licensee("SUPPLIER", legal_name="Upstream Fuel Supply LLC")
        distributor = world.new_licensee(
            "DISTRIBUTOR", legal_name="Empty Return Distribution Inc"
        )
        world.set_clock("2026-09-05T00:00:00Z")
        supplier_return = world.build_return(
            filer["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "GASOLINE",
                    "total": 800.00,
                    "lines": [
                        {
                            "counterparty": upstream["id"],
                            "gallons": 800.00,
                            "date": "2026-08-07",
                        }
                    ],
                }
            ],
        )
        empty_return = world.draft_return(distributor["id"], "2026-08")

        response = api.file_return(supplier_return.id, "N. Nosch", world.examiner)

        validate_error(response, ApiErrorId.MISSING_REQUIRED_SCHEDULE, expected_status=422)
        empty_response = api.file_return(empty_return["id"], "N. Nosch", world.examiner)
        validate_error(empty_response, ApiErrorId.MISSING_REQUIRED_SCHEDULE, expected_status=422)

        for return_id in (supplier_return.id, empty_return["id"]):
            reread = validate_success(api.get_return(return_id, world.examiner))
            assert_return_statuses(reread, "DRAFT", "NOT_MATCHED")
        _rows, meta = validate_paginated(
            api.list_returns(
                world.examiner,
                params={"period_month": "2026-08", "filing_status": "FILED"},
            )
        )
        assert_total_count(meta, 0, "filed returns of the period after both refusals")

        delivery = world.schedule(
            supplier_return.id, "SCH_5_DELIVERED_TAX_COLLECTED", "GASOLINE", 800.00
        )
        world.line(delivery["id"], distributor["id"], 800.00, "2026-08-11", transaction_type="SALE")
        filed = validate_success(
            api.file_return(supplier_return.id, "N. Nosch", world.examiner),
            expected_status=200,
        )
        assert_return_statuses(filed, "FILED")


class TestResolutionAndDutyGates:
    def test_a_variance_at_the_escalation_threshold_can_never_be_written_off(
        self, api, world, manager_headers
    ):
        """11000.00 gallons survived only because an overlapping case suppressed escalation.

        PRD: "It requires a `write_off_reason`, and it is permitted only when the absolute value of
        `variance_gallons` is strictly less than 10000.00 gallons; a variance at or above the
        auto-escalation threshold must be explained or escalated and can never be written off."
        PRD: "If, however, a non-closed audit case for that same subject already overlaps the run's
        period under the buffered-overlap rule of §3.9, no case is created: the discrepancy is left
        `OPEN`, it counts in the purchaser's `open_discrepancy_count` like any other open finding, and
        `escalation_skipped_count` increments instead."

        Design: Corner/validations/write_off_at_the_auto_escalation_threshold_returns_write_off_not_permitted
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Writeoff Fuel Supply LLC")
        purchaser = world.new_licensee("DISTRIBUTOR", legal_name="Writeoff Distribution Inc")
        world.audit_case(
            purchaser["id"],
            period_start_month="2026-08",
            period_end_month="2026-08",
            as_headers=manager_headers,
            selection_method="ROADSIDE_REFERRAL",
        )
        world.set_clock("2026-09-05T00:00:00Z")
        world.filed_return(
            supplier["id"],
            "2026-08",
            [
                {
                    "code": "SCH_5_DELIVERED_TAX_COLLECTED",
                    "product": "GASOLINE",
                    "total": 12000.00,
                    "lines": [
                        {
                            "counterparty": purchaser["id"],
                            "gallons": 12000.00,
                            "date": "2026-08-10",
                            "transaction_type": "SALE",
                        }
                    ],
                }
            ],
            attest_name="W. Writeoff",
        )
        world.filed_return(
            purchaser["id"],
            "2026-08",
            [
                {
                    "code": "SCH_1_RECEIVED_TAX_PAID",
                    "product": "GASOLINE",
                    "total": 1000.00,
                    "lines": [
                        {
                            "counterparty": supplier["id"],
                            "gallons": 1000.00,
                            "date": "2026-08-10",
                        }
                    ],
                }
            ],
            attest_name="W. Writeoff Dist",
        )
        run = world.run_cross_match("2026-08")
        assert run["escalation_skipped_count"] == 1
        discrepancy = world.only_discrepancy(run["id"])
        assert discrepancy["status"] == "OPEN"
        assert_gallons(discrepancy["variance_gallons"], 11000.00, "variance_gallons")

        response = api.resolve_discrepancy(
            discrepancy["id"],
            resolve_payload(
                "WRITTEN_OFF",
                write_off_reason="Counterparty ceased trading and the gallons are uncollectable",
            ),
            world.examiner,
        )

        validate_error(response, ApiErrorId.WRITE_OFF_NOT_PERMITTED, expected_status=422)
        unchanged = validate_success(api.get_discrepancy(discrepancy["id"], world.examiner))
        assert unchanged["status"] == "OPEN"
        assert_gallons(unchanged["variance_gallons"], 11000.00, "variance_gallons after refusal")
        run_reread = validate_success(api.get_cross_match_run(run["id"], world.examiner))
        assert_gallons(
            run_reread["unreported_gallons_total"], 11000.00, "unreported_gallons_total"
        )
        assert_gallons(
            run_reread["written_off_gallons_total"], 0.00, "written_off_gallons_total"
        )

        explained = validate_success(
            api.resolve_discrepancy(
                discrepancy["id"], resolve_payload("EXPLAINED"), world.examiner
            ),
            expected_status=200,
        )
        assert explained["status"] == "RESOLVED_EXPLAINED"

    def test_the_examiner_who_reviewed_a_claim_may_not_decide_it_even_as_a_supervisor(
        self, api, world, supervisor_headers, supervisor_alt_headers
    ):
        """The bar is on the acting X-User-ID, not on the role the caller presents.

        PRD: "A `TaxSupervisor` decides a `REVIEWED` claim by supplying a `decision`, and the acting
        `X-User-ID` must differ from the recorded `reviewer_user_id` — the same human may not review
        and then decide the same claim, and the attempt is refused with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 422)."
        PRD: "The acting `X-User-ID` must differ from the recorded `decider_user_id`, so the
        supervisor who decided a claim may not also pay it; that violation too is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/the_reviewer_of_a_claim_cannot_also_decide_it
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Duties Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Duties Distribution Inc")
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
                            "date": "2026-08-13",
                        }
                    ],
                }
            ],
            attest_name="D. Duties",
        )
        claim = world.refund_claim(claimant["id"], "2026-08", 100.00)
        world.review_claim(claim["id"], "APPROVE")

        response = api.decide_claim(
            claim["id"],
            {"decision": "APPROVED"},
            make_tax_supervisor_headers(RETURNS_EXAMINER_ID),
        )

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, expected_status=422)
        held_back = validate_success(api.get_refund_claim(claim["id"], world.examiner))
        assert held_back["status"] == "REVIEWED"
        assert held_back["reviewer_user_id"] == RETURNS_EXAMINER_ID
        assert held_back["decider_user_id"] is None

        decided = validate_success(
            api.decide_claim(claim["id"], {"decision": "APPROVED"}, supervisor_headers),
            expected_status=200,
        )
        assert decided["status"] == "APPROVED"
        assert decided["decider_user_id"] == TAX_SUPERVISOR_ID
        assert_claim_money(decided, 100.00, 3090)

        self_paid = api.pay_claim(
            claim["id"], {"payment_reference": "WARRANT-000123"}, supervisor_headers
        )
        validate_error(self_paid, ApiErrorId.SEGREGATION_OF_DUTIES, expected_status=422)
        paid = validate_success(
            api.pay_claim(
                claim["id"], {"payment_reference": "WARRANT-000123"}, supervisor_alt_headers
            ),
            expected_status=200,
        )
        assert paid["status"] == "PAID"

    def test_a_partial_decision_is_tested_against_the_recomputed_amount(
        self, api, world, supervisor_headers, officer_headers
    ):
        """60.00 recommended gallons recompute to 1854 cents, under the floor, and nothing is written.

        PRD: "`allowable_gallons` is set to `recommended_gallons` and `refund_amount_cents` is
        recomputed as the reduced gallons times 30.9, rounded half up once. The payability floor is
        then re-checked against the **recomputed** amount, so a reduction that drops the refund below
        2000 cents is refused with `ERR_REFUND_BELOW_MINIMUM` and nothing at all is written — neither
        the gallons nor the status nor `decider_user_id`."

        Design: Corner/validations/partial_decision_recomputing_below_the_minimum_returns_refund_below_minimum
        """
        supplier = world.new_licensee("SUPPLIER", legal_name="Minimum Fuel Supply LLC")
        claimant = world.new_licensee("DISTRIBUTOR", legal_name="Minimum Distribution Inc")
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
                            "date": "2026-08-13",
                        }
                    ],
                }
            ],
            attest_name="M. Minimum",
        )
        claim = world.refund_claim(claimant["id"], "2026-08", 100.00)
        world.review_claim(claim["id"], "PARTIAL", recommended_gallons=60.00)

        response = api.decide_claim(
            claim["id"], {"decision": "PARTIALLY_APPROVED"}, supervisor_headers
        )

        validate_error(response, ApiErrorId.REFUND_BELOW_MINIMUM, expected_status=422)
        untouched = validate_success(api.get_refund_claim(claim["id"], world.examiner))
        assert untouched["status"] == "REVIEWED"
        assert_claim_money(untouched, 100.00, 3090)
        assert untouched["decider_user_id"] is None

        approved = validate_success(
            api.decide_claim(claim["id"], {"decision": "APPROVED"}, supervisor_headers),
            expected_status=200,
        )
        assert_claim_money(approved, 100.00, 3090)

        _rows, meta = validate_paginated(
            api.list_ledger_entries(
                claimant["id"], officer_headers, params={"entry_type": "REFUND"}
            )
        )
        assert_total_count(meta, 0, "REFUND ledger rows before payment")

    def test_a_parent_licensee_must_be_an_active_top_level_supplier(
        self, api, world, officer_headers
    ):
        """Each conjunct of the group rule is independently fatal, and only the head is accepted.

        PRD: "Consolidated groups are exactly one level deep: a supplied `parent_licensee_id` must
        name a licensee whose `license_type` is `SUPPLIER`, whose `status` is `ACTIVE`, and whose own
        `parent_licensee_id` is null, and a licensee may never name itself."
        PRD: "Any of those failures is refused with `ERR_INVALID_PARENT_LICENSEE` (HTTP 422)."

        Design: Corner/validations/parent_licensee_must_be_an_active_top_level_supplier
        """
        head = world.active_licensee(
            "SUPPLIER", bond_cents=1500000, legal_name="Group Head Fuel Supply LLC"
        )
        pending = world.new_licensee("SUPPLIER", legal_name="Not Yet Fuel Supply LLC")
        middle = world.active_licensee(
            "SUPPLIER",
            bond_cents=1500000,
            legal_name="Mid Level Fuel Supply LLC",
            parent_licensee_id=head["id"],
        )

        response = api.create_licensee(
            licensee_payload(
                "DISTRIBUTOR",
                legal_name="Applicant One Distribution Inc",
                parent_licensee_id=pending["id"],
            ),
            officer_headers,
        )

        validate_error(response, ApiErrorId.INVALID_PARENT_LICENSEE, expected_status=422)

        under_a_child = api.create_licensee(
            licensee_payload(
                "DISTRIBUTOR",
                legal_name="Applicant Two Distribution Inc",
                parent_licensee_id=middle["id"],
            ),
            officer_headers,
        )
        validate_error(under_a_child, ApiErrorId.INVALID_PARENT_LICENSEE, expected_status=422)

        accepted = validate_success(
            api.create_licensee(
                licensee_payload(
                    "DISTRIBUTOR",
                    legal_name="Applicant Three Distribution Inc",
                    parent_licensee_id=head["id"],
                ),
                officer_headers,
            ),
            expected_status=201,
        )
        assert accepted["parent_licensee_id"] == head["id"]

        _rows, meta = validate_paginated(
            api.list_licensees(officer_headers, params={"parent_licensee_id": head["id"]})
        )
        assert_total_count(meta, 2, "members of the consolidated group")
