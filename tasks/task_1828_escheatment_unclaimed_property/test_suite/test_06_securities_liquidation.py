"""Securities detail, liquidation workflow, dual-variant valuation, and the
settle cascade (PRD §3.5)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)
from test_helpers.factories import create_securities_detail_payload
from test_helpers.fixtures import (
    CO,
    READER,
    TO,
    create_owner,
    create_property,
    create_report,
    create_reportable_property,
    create_rule,
    get_property,
    get_report,
    send_letter,
    set_clock,
    setup_reported_securities_property,
    setup_remitted_securities_property,
    add_line_item,
    create_remittance,
    confirm_remittance,
    make_claimant_headers,
    run_sweep,
)

CO_H = TEST_USERS["compliance_officer_headers"]
TO_H = TEST_USERS["treasury_ops_headers"]
SA_H = TEST_USERS["state_auditor_headers"]

SEC_KW = {"cusip": "ESC1828A", "shares_quantity": 100,
          "last_close_price_cents": 4500, "accrued_dividends_cents": 12500}


class TestSecuritiesDetailRegistration:
    def test_duplicate_securities_detail_rejected(self, api):
        """PRD §3.5: "The relationship is one-to-one: a property that already
        has a detail refuses a second with `ERR_SECURITIES_DETAIL_EXISTS`."

        Design: Corner/errors/duplicate_securities_detail_rejected
        """
        create_rule(state_code="NV", property_type="BROKERAGE_SHARES")
        owner = create_owner(state_code="NV")
        prop = create_property(owner["id"], property_type="BROKERAGE_SHARES",
                               state_code="NV", original_value_cents=462500)
        first = get_success_data(
            api.create_securities_detail(
                prop["id"], create_securities_detail_payload(**SEC_KW), CO_H
            ),
            201,
        )
        resp = api.create_securities_detail(
            prop["id"],
            create_securities_detail_payload(
                cusip="ESC1828H", shares_quantity=50,
                last_close_price_cents=4000, accrued_dividends_cents=0,
            ),
            CO_H,
        )
        validate_error(resp, ApiErrorId.ERR_SECURITIES_DETAIL_EXISTS, 409)
        detail = get_success_data(api.get_securities_detail(prop["id"], READER), 200)
        assert detail[0]["shares_quantity"] == 100
        assert detail[0]["last_close_price_cents"] == 4500

    def test_securities_detail_on_cash_property_rejected(self, api):
        """PRD §3.5: "A `ComplianceOfficer` registers a **securities detail**
        on a property whose type is `BROKERAGE_SHARES` — attempting it on any
        other property type is refused with `ERR_NOT_SECURITIES_PROPERTY`"

        Design: Corner/errors/securities_detail_on_cash_property_rejected
        """
        create_rule()
        owner = create_owner()
        prop = create_property(owner["id"], original_value_cents=50000)
        resp = api.create_securities_detail(
            prop["id"],
            create_securities_detail_payload(
                cusip="ESC1828I", shares_quantity=10,
                last_close_price_cents=1000, accrued_dividends_cents=0,
            ),
            CO_H,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_SECURITIES_PROPERTY, 422)

    def test_securities_line_requires_detail(self, api):
        """PRD §3.4: "and a `BROKERAGE_SHARES` property must already carry its
        securities detail, else `ERR_SECURITIES_DETAIL_REQUIRED`."

        Design: Corner/errors/securities_line_without_detail_rejected
        """
        _, _, prop, _ = create_reportable_property(
            state_code="NV", property_type="BROKERAGE_SHARES",
            original_value_cents=462500,
        )
        report = create_report(state_code="NV")
        before = get_report(report["id"])["version"]
        resp = api.add_line_item(
            report["id"],
            {"property_id": prop["id"], "expected_report_version": before},
            CO_H,
        )
        validate_error(resp, ApiErrorId.ERR_SECURITIES_DETAIL_REQUIRED, 422)
        assert get_report(report["id"])["version"] == before, (
            "a rejected line add leaves the report untouched"
        )


class TestLiquidationRequestGates:
    def test_liquidation_before_reported_rejected(self, api):
        """PRD §3.5: "The property must be `REPORTED` — meaning it rides an
        `ACCEPTED` report — else `ERR_PROPERTY_NOT_REPORTED`"

        Design: Corner/errors/liquidation_before_reported_rejected
        """
        _, _, prop, _ = create_reportable_property(
            state_code="NV", property_type="BROKERAGE_SHARES",
            original_value_cents=462500, with_securities=SEC_KW,
        )
        resp = api.create_liquidation_order(
            {"property_id": prop["id"], "liquidation_fee_cents": 2500}, TO_H
        )
        validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_REPORTED, 422)

    def test_duplicate_active_liquidation_rejected(self, api):
        """PRD §3.5: "no other non-terminal order — one in `REQUESTED` or
        `EXECUTED` — may exist for the property, else
        `ERR_DUPLICATE_ACTIVE_LIQUIDATION`."

        Design: Corner/errors/duplicate_active_liquidation_rejected
        """
        chain = setup_reported_securities_property()
        first = get_success_data(
            api.create_liquidation_order(
                {"property_id": chain["property"]["id"],
                 "liquidation_fee_cents": 2500},
                TO_H,
            ),
            201,
        )
        resp = api.create_liquidation_order(
            {"property_id": chain["property"]["id"],
             "liquidation_fee_cents": 3000},
            TO_H,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_LIQUIDATION, 409)
        still = get_success_data(api.get_liquidation_order(first["id"], READER), 200)
        assert still["status"] == "REQUESTED"

    def test_settle_from_requested_rejected(self, api):
        """PRD §3.5: "Settling an `EXECUTED` order — any other state is
        `ERR_LIQUIDATION_INVALID_STATE` — stamps `settled_date` with the clock
        date and computes `net_proceeds_cents`"

        Design: Corner/state_machines/liquidation_settle_from_requested_rejected
        """
        chain = setup_reported_securities_property()
        order = get_success_data(
            api.create_liquidation_order(
                {"property_id": chain["property"]["id"],
                 "liquidation_fee_cents": 2500},
                TO_H,
            ),
            201,
        )
        resp = api.settle_liquidation_order(order["id"], TO_H)
        validate_error(resp, ApiErrorId.ERR_LIQUIDATION_INVALID_STATE, 409)
        still = get_success_data(api.get_liquidation_order(order["id"], READER), 200)
        assert still["status"] == "REQUESTED"
        lines, _ = validate_paginated(
            api.list_line_items(chain["report"]["id"], READER)
        )
        assert lines[0]["status"] == "INCLUDED"
        assert lines[0]["final_value_cents"] is None

    def test_fee_exceeding_gross_plus_dividends_rejected(self, api):
        """PRD §3.5: "the fee may not exceed the gross plus dividends, so a
        `liquidation_fee_cents` greater than the execution price times the
        share quantity plus the `accrued_dividends_cents` is refused with
        `ERR_LIQUIDATION_FEE_EXCEEDS_GROSS`, with equality expressly allowed
        since net proceeds floor at zero."

        Design: Corner/errors/liquidation_fee_exceeds_gross_rejected
        """
        chain = setup_reported_securities_property(
            shares=10, close_price=1000, dividends=500, original_value_cents=10500,
            cusip="ESC1828K",
        )
        order = get_success_data(
            api.create_liquidation_order(
                {"property_id": chain["property"]["id"],
                 "liquidation_fee_cents": 10501},
                TO_H,
            ),
            201,
        )
        # gross 10*1000 = 10000; 10501 > 10000 + 500.
        resp = api.execute_liquidation_order(
            order["id"], {"execution_price_cents_per_share": 1000}, TO_H
        )
        validate_error(resp, ApiErrorId.ERR_LIQUIDATION_FEE_EXCEEDS_GROSS, 422)
        still = get_success_data(api.get_liquidation_order(order["id"], READER), 200)
        assert still["status"] == "REQUESTED"

    def test_execution_window_boundary(self, api):
        """PRD §3.5: "the execution may occur no later than sixty days after
        the `due_date` of the accepted report containing the property — a clock
        date on or before that day passes, anything later is refused with
        `ERR_LIQUIDATION_WINDOW_VIOLATION`"

        Design: Corner/errors/liquidation_window_violation_rejected
        """
        chain = setup_reported_securities_property(cusip="ESC1828L")
        prop_id = chain["property"]["id"]
        order1 = get_success_data(
            api.create_liquidation_order(
                {"property_id": prop_id, "liquidation_fee_cents": 2500}, TO_H
            ),
            201,
        )
        set_clock("2026-12-31T00:00:00Z")  # due_date 2026-11-01 + 60 days
        executed = get_success_data(
            api.execute_liquidation_order(
                order1["id"], {"execution_price_cents_per_share": 4700}, TO_H
            ),
            200,
        )
        assert executed["status"] == "EXECUTED", "boundary day is inclusive"
        get_success_data(api.cancel_liquidation_order(order1["id"], TO_H), 200)
        order2 = get_success_data(
            api.create_liquidation_order(
                {"property_id": prop_id, "liquidation_fee_cents": 2500}, TO_H
            ),
            201,
        )
        set_clock("2027-01-01T00:00:00Z")
        resp = api.execute_liquidation_order(
            order2["id"], {"execution_price_cents_per_share": 4700}, TO_H
        )
        validate_error(resp, ApiErrorId.ERR_LIQUIDATION_WINDOW_VIOLATION, 409)
        still = get_success_data(api.get_liquidation_order(order2["id"], READER), 200)
        assert still["status"] == "REQUESTED"


class TestDualVariantValuation:
    def test_provisional_variant_at_line_inclusion(self, api):
        """PRD §3.5: "The **provisional** variant runs at line-item inclusion
        into a draft report and values the position at its last known close:
        the `last_close_price_cents` multiplied by the `shares_quantity`, plus
        the `accrued_dividends_cents`, with no fee deduction."

        Design: Difficulty/dual_variant_calc/securities_valuation_provisional_vs_liquidation_final
        """
        _, _, prop, _ = create_reportable_property(
            state_code="NV", property_type="BROKERAGE_SHARES",
            original_value_cents=462500, with_securities=SEC_KW,
        )
        report = create_report(state_code="NV")
        line = add_line_item(report["id"], prop["id"])
        assert line["line_type"] == "SECURITIES"
        assert line["provisional_value_cents"] == 462500  # 100*4500 + 12500
        assert line["final_value_cents"] is None
        report_now = get_report(report["id"])
        assert report_now["total_provisional_cents"] == 462500

    def test_final_variant_at_liquidation_settle(self, api):
        """PRD §3.5: "The **final** variant runs at liquidation settlement and
        values the position at its actual execution: the
        `execution_price_cents_per_share` multiplied by the `shares_quantity`,
        minus the `liquidation_fee_cents`, plus the `accrued_dividends_cents`,
        floored at zero."

        Design: Difficulty/dual_variant_calc/securities_valuation_provisional_vs_liquidation_final
        """
        chain = setup_reported_securities_property()
        order = get_success_data(
            api.create_liquidation_order(
                {"property_id": chain["property"]["id"],
                 "liquidation_fee_cents": 2500},
                TO_H,
            ),
            201,
        )
        get_success_data(
            api.execute_liquidation_order(
                order["id"], {"execution_price_cents_per_share": 4700}, TO_H
            ),
            200,
        )
        settled = get_success_data(api.settle_liquidation_order(order["id"], TO_H), 200)
        assert settled["net_proceeds_cents"] == 480000  # 100*4700 - 2500 + 12500
        assert settled["gross_proceeds_cents"] == 470000
        lines, _ = validate_paginated(
            api.list_line_items(chain["report"]["id"], READER)
        )
        assert lines[0]["status"] == "FINAL"
        assert lines[0]["final_value_cents"] == 480000
        report = get_report(chain["report"]["id"])
        assert report["total_provisional_cents"] == 462500, (
            "settle must not rewrite the provisional total"
        )
        assert report["total_final_cents"] == 480000
        # The two variants diverge for identical share/dividend inputs.
        assert 480000 - 462500 == 17500


class TestSettleCascade:
    def _executed_order_with_pending_remittance(self):
        chain = setup_reported_securities_property()
        order = get_success_data(
            api_client.create_liquidation_order(
                {"property_id": chain["property"]["id"],
                 "liquidation_fee_cents": 2500},
                TO_H,
            ),
            201,
        )
        # Remittance staged at the provisional total BEFORE settle.
        remittance = create_remittance(chain["report"]["id"], 462500)
        get_success_data(
            api_client.execute_liquidation_order(
                order["id"], {"execution_price_cents_per_share": 4700}, TO_H
            ),
            200,
        )
        return chain, order, remittance

    def test_settle_finalizes_line_and_report_total(self, api):
        """PRD §3.5: "The cascade then runs four hops: the property's
        `INCLUDED` report line moves to `FINAL` with its `final_value_cents`
        set to the `net_proceeds_cents`; the containing report recomputes
        `total_final_cents` — `total_provisional_cents` is unchanged — and its
        `version` increments"

        Design: Difficulty/transitive_cascade/liquidation_settle_cascade_line_report_remittance
        """
        chain, order, _ = self._executed_order_with_pending_remittance()
        get_success_data(api.settle_liquidation_order(order["id"], TO_H), 200)
        lines, _ = validate_paginated(
            api.list_line_items(chain["report"]["id"], READER)
        )
        assert lines[0]["status"] == "FINAL"
        assert lines[0]["final_value_cents"] == 480000
        report = get_report(chain["report"]["id"])
        assert report["total_final_cents"] == 480000
        assert report["total_provisional_cents"] == 462500

    def test_settle_recomputes_pending_remittance_variance(self, api):
        """PRD §3.5: "any `PENDING` remittance for that report recomputes its
        `variance_cents` against the new final total"
        PRD §3.6: "the `variance_cents` — the `amount_cents` minus the report's
        `total_final_cents`, evaluated at confirm time — is exactly zero (else
        `ERR_REMITTANCE_VARIANCE_NONZERO`)."

        Design: Difficulty/transitive_cascade/liquidation_settle_cascade_line_report_remittance
        """
        chain, order, remittance = self._executed_order_with_pending_remittance()
        get_success_data(api.settle_liquidation_order(order["id"], TO_H), 200)
        staged = get_success_data(api.get_remittance(remittance["id"], READER), 200)
        assert staged["variance_cents"] == -17500  # 462500 - 480000
        bad = api.confirm_remittance(remittance["id"], SA_H)
        validate_error(bad, ApiErrorId.ERR_REMITTANCE_VARIANCE_NONZERO, 422)
        get_success_data(
            api.fail_remittance(
                remittance["id"], {"failure_reason": "amount mismatch"}, SA_H
            ),
            200,
        )
        get_success_data(
            api.requeue_remittance(remittance["id"], {"amount_cents": 480000}, TO_H),
            200,
        )
        confirmed = get_success_data(
            api.confirm_remittance(remittance["id"], SA_H), 200
        )
        assert confirmed["status"] == "CONFIRMED"
        assert get_property(chain["property"]["id"])["status"] == "REMITTED"


class TestExecuteCancelCompensation:
    def test_cancel_unstages_pending_execution(self, api):
        """PRD §3.5: "Execution stamps `executed_date` with the clock date,
        computes `gross_proceeds_cents` as the execution price times the
        `shares_quantity`, and stages the detail: `REGISTERED →
        EXECUTION_PENDING`, with `pending_execution_price_cents` holding the
        execution price."
        PRD §3.5: "Cancelling from `EXECUTED` — the same
        `ERR_LIQUIDATION_INVALID_STATE` guards any other origin — runs a
        compensating reversal: the detail returns `EXECUTION_PENDING →
        REGISTERED`, its `pending_execution_price_cents` clears to null"

        Design: Difficulty/compensating_invariant/liquidation_execute_cancel_conserves_line_valuation
        """
        chain = setup_reported_securities_property(cusip="ESC1828D")
        order = get_success_data(
            api.create_liquidation_order(
                {"property_id": chain["property"]["id"],
                 "liquidation_fee_cents": 2500},
                TO_H,
            ),
            201,
        )
        get_success_data(
            api.execute_liquidation_order(
                order["id"], {"execution_price_cents_per_share": 4700}, TO_H
            ),
            200,
        )
        mid = get_success_data(
            api.get_securities_detail(chain["property"]["id"], READER), 200
        )
        assert mid[0]["status"] == "EXECUTION_PENDING"
        assert mid[0]["pending_execution_price_cents"] == 4700
        cancelled = get_success_data(api.cancel_liquidation_order(order["id"], TO_H), 200)
        assert cancelled["status"] == "CANCELLED"
        after = get_success_data(
            api.get_securities_detail(chain["property"]["id"], READER), 200
        )
        assert after[0]["status"] == "REGISTERED"
        assert after[0]["pending_execution_price_cents"] is None

    def test_execute_cancel_conserves_line_valuation(self, api):
        """PRD §3.5: "and, as the compensating invariant, the report line's
        `provisional_value_cents` and status are left exactly as they were, so
        an included securities line survives a cancelled execution with its
        provisional value intact."

        Design: Difficulty/compensating_invariant/liquidation_execute_cancel_conserves_line_valuation
        """
        chain = setup_reported_securities_property(cusip="ESC1828D")
        order = get_success_data(
            api.create_liquidation_order(
                {"property_id": chain["property"]["id"],
                 "liquidation_fee_cents": 2500},
                TO_H,
            ),
            201,
        )
        get_success_data(
            api.execute_liquidation_order(
                order["id"], {"execution_price_cents_per_share": 4700}, TO_H
            ),
            200,
        )
        get_success_data(api.cancel_liquidation_order(order["id"], TO_H), 200)
        lines, _ = validate_paginated(
            api.list_line_items(chain["report"]["id"], READER)
        )
        assert lines[0]["status"] == "INCLUDED"
        assert lines[0]["provisional_value_cents"] == 462500
        assert lines[0]["final_value_cents"] is None
        assert get_report(chain["report"]["id"])["total_provisional_cents"] == 462500


class TestZeroNetProceeds:
    def test_zero_net_proceeds_blocks_claim(self, api):
        """PRD §3.5: "a `liquidation_fee_cents` greater than the execution
        price times the share quantity plus the `accrued_dividends_cents` is
        refused with `ERR_LIQUIDATION_FEE_EXCEEDS_GROSS`, with equality
        expressly allowed since net proceeds floor at zero."
        PRD §3.7: "the recoverable base — the property's remitted line value
        for cash, or its settled liquidation net proceeds for securities,
        exactly the base the payout computation below will use — must be
        greater than zero, so a claim on a position liquidated to zero net
        proceeds is refused with `ERR_CLAIM_EXCEEDS_RECOVERABLE`."

        Design: Corner/calculations/claim_zero_net_proceeds_blocks_claim
        """
        chain = setup_remitted_securities_property(
            shares=10, close_price=1000, dividends=500, fee=10500,
            exec_price=1000, original_value_cents=10500,
        )
        # fee 10500 == gross 10000 + dividends 500 -> allowed; net floors at 0.
        assert chain["order"]["net_proceeds_cents"] == 0
        assert get_property(chain["property"]["id"])["status"] == "REMITTED"
        resp = api.create_claim(
            {"property_id": chain["property"]["id"]},
            make_claimant_headers(chain["owner"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_RECOVERABLE, 422)
