"""Report delivery: fee variants, considerability rules, first-match matrix
evaluation, and post-delivery counters."""
from test_helpers import (
    ApiErrorId,
    create_report_payload,
    finding,
    get_success_data,
    get_vendor_record,
    list_report_findings,
    make_vendor_agent_headers,
    setup_dispatched_order,
    setup_report_received,
    validate_error,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestOrderFeeDualVariant:
    def test_provisional_fee_frozen_at_dispatch_without_credit(self, api):
        """PRD section "Dispatch, the SLA Clock, and Vendor Capacity": "freezes
        `provisional_fee_cents` as the package's `fee_cents` plus the vendor's
        `surcharge_cents`" and "From dispatch until delivery, reads of the order
        expose the provisional fee; no SLA credit can be known yet."

        Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_with_sla_credit
        """
        ctx = setup_dispatched_order(
            tag="DV1",
            with_matrix=False,
            package_overrides={"fee_cents": 25000, "tat_business_hours": 8},
            vendor_overrides={"surcharge_cents": 0},
            dispatch_at="2026-08-05T10:00:00Z",
        )
        order = ctx["order"]
        assert order["provisional_fee_cents"] == 25000
        assert order["final_fee_cents"] is None

    def test_final_fee_applies_sla_credit_on_late_delivery(self, api):
        """PRD section "Report Delivery": "For an `INITIAL` order delivered in
        breach, the final fee is the provisional fee minus a ten-percent SLA
        credit, the credit computed by integer floor of one-tenth of the
        provisional amount, with the result floored at zero; an on-time delivery
        simply carries the provisional amount forward." and "`sla_breached` is
        true exactly when the turnaround is strictly greater than the package's
        `tat_business_hours`"."

        Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_with_sla_credit
        """
        # Dispatch Wed 2026-08-05T10:00, tat 8 -> due Thu 10:00; deliver Thu
        # 11:00 => turnaround 9.0 > 8 => breach; final = 25000 - 2500 = 22500.
        # An ACTIVE matrix must exist: report delivery requires one (PRD
        # "Configuring the Screening Catalog").
        ctx = setup_dispatched_order(
            tag="DV1B",
            package_overrides={"fee_cents": 25000, "tat_business_hours": 8},
            vendor_overrides={"surcharge_cents": 0},
            dispatch_at="2026-08-05T10:00:00Z",
        )
        get_success_data(api.set_clock("2026-08-06T11:00:00Z"))
        report = validate_success(
            api.create_report(
                create_report_payload(ctx["order"]["id"], findings=[]),
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            ),
            expected_status=201,
        )
        assert report["sla_breached"] is True

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["provisional_fee_cents"] == 25000
        assert order["final_fee_cents"] == 22500


class TestFirstMatchRuleOrdering:
    RULES = [
        {
            "offense_category": "NONVIOLENT_FELONY",
            "min_severity": "LOW",
            "max_recency_years": 99,
            "action": "IA_REQUIRED",
        },
        {
            "offense_category": "NONVIOLENT_FELONY",
            "min_severity": "HIGH",
            "max_recency_years": 5,
            "action": "ADVERSE_ELIGIBLE",
        },
    ]
    FINDINGS = [
        finding(
            offense_category="NONVIOLENT_FELONY",
            severity="HIGH",
            offense_date="2023-08-01T00:00:00Z",
        )
    ]

    def test_first_matching_rule_wins_on_finding(self, api):
        """PRD section "Report Delivery": "the matrix's ordered rules are
        scanned in declared array order and the first rule whose
        `offense_category` equals the finding's, whose `min_severity` is at or
        below the finding's severity on the `LOW` < `MEDIUM` < `HIGH` scale, and
        whose `max_recency_years` is at least the finding's recency" supplies
        the finding's `matched_action`.

        Design: Difficulty/combinatorial_formula/adjudication_first_match_rule_ordering
        """
        ctx = setup_report_received(
            tag="CF1",
            matrix_rules=self.RULES,
            findings=self.FINDINGS,
            deliver_at="2026-08-06T10:00:00Z",
        )
        findings = list_report_findings(ctx["report"]["id"], HR)
        assert len(findings) == 1
        # Offense 2023-08-01 is after the 7-year cutoff 2019-08-06: considerable.
        assert findings[0]["considerable"] is True
        # Both rules match (HIGH >= LOW and >= HIGH; recency 3 <= 99 and <= 5);
        # the first array element wins.
        assert findings[0]["matched_action"] == "IA_REQUIRED"

    def test_first_match_drives_order_recommended_outcome(self, api):
        """PRD section "Report Delivery": "The order's `recommended_outcome` is
        the worst `matched_action` across considerable findings, with
        `ADVERSE_ELIGIBLE` outranking `IA_REQUIRED` outranking `CLEAR`"."

        Design: Difficulty/combinatorial_formula/adjudication_first_match_rule_ordering
        """
        ctx = setup_report_received(
            tag="CF1B",
            matrix_rules=self.RULES,
            findings=self.FINDINGS,
            deliver_at="2026-08-06T10:00:00Z",
        )
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["recommended_outcome"] == "IA_REQUIRED"
        assert order["adjudication_status"] == "PENDING_REVIEW"


class TestConsiderability:
    def test_lookback_cutoff_inclusive_boundary(self, api):
        """PRD section "Report Delivery": "any `CONVICTION` whose `offense_date`
        falls strictly before the lookback cutoff — the date of delivery minus
        the jurisdiction's `lookback_years_limit`, computed by calendar
        anniversary" is excluded, and "A conviction dated exactly on the cutoff
        remains considerable; the comparison is strictly-before."

        Design: Corner/calculations/lookback_cutoff_inclusive_boundary
        """
        # Delivery 2026-08-06, lookback 7 years -> cutoff 2019-08-06.
        ctx = setup_report_received(
            tag="CC3",
            matrix_rules=[
                {
                    "offense_category": "MISDEMEANOR",
                    "min_severity": "LOW",
                    "max_recency_years": 99,
                    "action": "ADVERSE_ELIGIBLE",
                }
            ],
            findings=[
                finding(
                    offense_category="MISDEMEANOR", severity="LOW",
                    offense_date="2019-08-06T00:00:00Z",
                ),
                finding(
                    offense_category="MISDEMEANOR", severity="LOW",
                    offense_date="2019-08-05T00:00:00Z",
                ),
            ],
            deliver_at="2026-08-06T10:00:00Z",
        )
        findings = list_report_findings(ctx["report"]["id"], HR)
        by_date = {f["offense_date"][:10]: f for f in findings}
        assert by_date["2019-08-06"]["considerable"] is True
        assert by_date["2019-08-05"]["considerable"] is False

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["recommended_outcome"] == "ADVERSE_ELIGIBLE"

    def test_arrest_records_excluded_by_jurisdiction(self, api):
        """PRD section "Report Delivery": "Considerability excludes two classes
        of finding: any finding with `disposition` `ARREST_ONLY` when the
        jurisdiction has `arrest_records_considerable` set false" and "A finding
        that matches no rule defaults its `matched_action` to `CLEAR`, as does
        any non-considerable finding." and "an order whose considerable set is
        empty recommends `CLEAR`."

        Design: Corner/calculations/arrest_records_excluded_by_jurisdiction
        """
        ctx = setup_report_received(
            tag="CC4",
            jurisdiction_code="US-IL",
            jurisdiction_overrides={"arrest_records_considerable": False},
            matrix_rules=[
                {
                    "offense_category": "ARREST_NO_CONVICTION",
                    "min_severity": "LOW",
                    "max_recency_years": 99,
                    "action": "ADVERSE_ELIGIBLE",
                }
            ],
            findings=[
                finding(
                    offense_category="ARREST_NO_CONVICTION",
                    severity="HIGH",
                    offense_date="2025-01-10T00:00:00Z",
                    disposition="ARREST_ONLY",
                )
            ],
            deliver_at="2026-08-06T10:00:00Z",
        )
        findings = list_report_findings(ctx["report"]["id"], HR)
        assert len(findings) == 1
        assert findings[0]["considerable"] is False
        # A non-considerable finding defaults its matched_action to CLEAR.
        assert findings[0]["matched_action"] == "CLEAR"

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["recommended_outcome"] == "CLEAR"

    def test_salary_exemption_disables_lookback(self, api):
        """PRD section "Report Delivery": "unless the salary exemption applies
        (the jurisdiction's `lookback_exemption_salary_cents` is positive and
        the position's `annual_salary_cents` meets or exceeds it)" and PRD
        section "Configuring the Screening Catalog": "a
        `lookback_exemption_salary_cents` threshold defaulting to zero, where a
        positive value exempts positions whose salary meets or exceeds it from
        the lookback limit"."

        Design: Corner/calculations/salary_exemption_disables_lookback
        """
        # Salary exactly equal to the exemption threshold: exempt (>=), so the
        # 11-year-old conviction stays considerable.
        ctx = setup_report_received(
            tag="CC5",
            jurisdiction_overrides={"lookback_exemption_salary_cents": 12500000},
            position_overrides={"annual_salary_cents": 12500000},
            matrix_rules=[
                {
                    "offense_category": "NONVIOLENT_FELONY",
                    "min_severity": "LOW",
                    "max_recency_years": 99,
                    "action": "IA_REQUIRED",
                }
            ],
            findings=[
                finding(
                    offense_category="NONVIOLENT_FELONY",
                    severity="MEDIUM",
                    offense_date="2015-03-01T00:00:00Z",
                )
            ],
            deliver_at="2026-08-06T10:00:00Z",
        )
        findings = list_report_findings(ctx["report"]["id"], HR)
        assert findings[0]["considerable"] is True
        assert findings[0]["matched_action"] == "IA_REQUIRED"

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["recommended_outcome"] == "IA_REQUIRED"


class TestDeliveryGatesAndCounters:
    def test_report_delivery_requires_active_matrix(self, api):
        """PRD section "Configuring the Screening Catalog": "Retirement moves an
        `ACTIVE` matrix to `RETIRED` (a non-active matrix rejects with
        `ERR_MATRIX_NOT_ACTIVE`) without disturbing any order that already
        pinned it — pinned evaluations survive retirement — but future report
        deliveries for that tier will then fail for lack of an active matrix."

        Design: Corner/validations/report_delivery_requires_active_matrix
        """
        ctx = setup_dispatched_order(tag="VL14", dispatch_at="2026-08-05T10:00:00Z")
        validate_success(api.retire_matrix(ctx["matrix"]["id"], CO))

        resp = api.create_report(
            create_report_payload(ctx["order"]["id"], findings=[]),
            make_vendor_agent_headers(ctx["vendor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MATRIX_NOT_ACTIVE)

        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["fulfillment_status"] == "DISPATCHED"
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 1

    def test_vendor_breach_counter_and_derived_count_after_delivery(self, api):
        """PRD section "Report Delivery": "The vendor's `active_order_count`
        decrements by one. A breached SLA increments `consecutive_sla_breaches`;
        an on-time delivery resets the counter to zero"."

        Design: Corner/calculations/vendor_breach_counter_and_derived_count_after_delivery
        """
        ctx = setup_dispatched_order(tag="CC10", dispatch_at="2026-08-05T10:00:00Z")
        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 1

        get_success_data(api.set_clock("2026-08-06T10:00:00Z"))
        report = validate_success(
            api.create_report(
                create_report_payload(ctx["order"]["id"], findings=[]),
                make_vendor_agent_headers(ctx["vendor"]["id"]),
            ),
            expected_status=201,
        )
        assert report["sla_breached"] is False

        vendor = get_vendor_record(ctx["vendor"]["id"])
        assert vendor["active_order_count"] == 0
        assert vendor["consecutive_sla_breaches"] == 0

    def test_cancel_after_report_received_rejected(self, api):
        """PRD section "Cancellation, Revocation, and Withdrawal Cascades": "A
        `HiringManager` may cancel an order while its fulfillment is `DRAFT`,
        `CONSENT_CAPTURED`, or `DISPATCHED`; any other state rejects with
        `ERR_ORDER_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_after_report_received_rejected
        """
        ctx = setup_report_received(
            tag="SM3", findings=[], deliver_at="2026-08-06T10:00:00Z"
        )
        resp = api.cancel_order(ctx["order"]["id"], HM)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        order = get_success_data(api.get_order(ctx["order"]["id"], HR))
        assert order["fulfillment_status"] == "REPORT_RECEIVED"
