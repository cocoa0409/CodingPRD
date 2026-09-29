"""Ordered-gauntlet precedence and last-digit boundaries.

The first half pins which rejection wins when a single request violates two
rules that sit in different bands of the ordered validation gauntlet. The second
half walks the numeric boundaries whose admissible answer changes on the last
digit: the inclusive penetration floor, the inclusive underreporting penalty
step, a licence fee landing on exactly half a cent, and the inclusive lower
bound of the co-op ceiling band.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    accept_report,
    agreement_version,
    api_client,
    attach_mfn_clause,
    create_commitment,
    create_invoice_payload,
    distributor_version,
    draft_agreement,
    earn_commitment,
    execute_agreement,
    fetch_agreement,
    fetch_commitment,
    file_report,
    get_success_data,
    make_affiliate_sales_exec_headers,
    record_finding,
    register_distributor,
    schedule_blackout,
    setup_engagement_in_fieldwork,
    setup_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

NORTHGATE_OPERATOR = {
    "legal_name": "Northgate Cable Systems",
    "distributor_type": "CABLE_MSO",
    "rate_card_class": "CLASS_A",
    "total_subscribers": 4_000_000,
    "credit_limit_cents": 500_000_000,
}

NORTHGATE_TERMS = {
    "contract_code": "NG-2024-01",
    "term_start_date": "2024-01-01T00:00:00Z",
    "term_end_date": "2027-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 42.0000,
    "escalator_pct": 0.04,
    "penetration_floor_pct": 0.85,
    "committed_tier": "EXPANDED_BASIC",
    "launch_fee_cents": 0,
    "marketing_commitment_cents": 0,
}


class TestRoleGateBeforePathExistence:
    """The endpoint's role gate is evaluated before the report id is resolved."""

    def test_forbidden_role_precedes_report_not_found(self, api, audit_manager_headers):
        """PRD §2.1: "If both headers are well-formed but the named role is not
        among the roles authorised for the endpoint being called (see the table in
        §4), the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.8: "2. Endpoint role membership — `ERR_FORBIDDEN_ROLE`."
        PRD §2.8: "6. Existence of the path-addressed resource (rule 10 in the
        internal numbering)."
        PRD §5: "The rejection order among these codes is fixed by §2.8:
        authentication, then role authorisation, then request shape, then
        path-parameter existence, then body-reference existence, then revision
        guards, then segregation of duties and operator scope, then the entity's own
        state, then referenced-entity state, then referential integrity, then
        temporal rules, then fiscal rules."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_precedes_report_not_found
        """
        register_distributor()

        validate_error(
            api.review_subscriber_report(
                NON_EXISTENT_UUID, {"action": "ACCEPT"}, audit_manager_headers
            ),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

    def test_authorised_role_on_the_same_missing_report_gets_not_found(
        self, api, revenue_accountant_headers
    ):
        """PRD §2.8: "Path parameters are resolved left to right, and the first
        unresolvable segment decides the response."
        PRD §2.8: "The path identifiers used across the API are `distributorId`,
        `agreementId`, `rateCardEntryId`, `mfnClauseId`, `reportId`, `engagementId`,
        `findingId`, `titleId`, `windowId`, `blackoutRuleId`, `commitmentId`,
        `invoiceId` and `analysisId`, and each has its own not-found code:
        `ERR_DISTRIBUTOR_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
        `ERR_RATE_CARD_ENTRY_NOT_FOUND`, `ERR_MFN_CLAUSE_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
        `ERR_TITLE_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_BLACKOUT_NOT_FOUND`,
        `ERR_COMMITMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and
        `ERR_ANALYSIS_NOT_FOUND`, all HTTP 404."

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_precedes_report_not_found
        """
        register_distributor()

        rows, meta = validate_paginated(
            api.list_subscriber_reports(revenue_accountant_headers)
        )
        assert rows == [], f"no report was ever filed, got {rows}"
        assert meta["total_count"] == 0, (
            f"the identifier under test was never allocated, got total_count {meta['total_count']}"
        )

        validate_error(
            api.review_subscriber_report(
                NON_EXISTENT_UUID, {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            "ERR_REPORT_NOT_FOUND",
            404,
        )


def _setup_agreement_with_waived_mfn_clause():
    """An executed Northgate agreement whose only MFN clause has since been
    waived, so the clause is no longer resettable.

    Returns (distributor, agreement, clause).
    """
    distributor, agreement = setup_executed_agreement(
        NORTHGATE_OPERATOR, dict(NORTHGATE_TERMS)
    )
    clause = attach_mfn_clause(
        agreement["id"],
        mfn_scope="DOMESTIC",
        min_peer_subscribers=1_000_000,
        rate_floor_cents=30.0000,
    )
    waived = get_success_data(
        api_client.reset_mfn_clause(
            clause["id"],
            {
                "action": "WAIVE",
                "expected_agreement_version": agreement_version(agreement["id"]),
            },
            make_affiliate_sales_exec_headers(),
        )
    )
    return distributor, agreement, waived


class TestRevisionGuardBeforeOwnEntityState:
    """The parent-revision guard on an MFN reset is evaluated before the
    clause's own status."""

    def test_stale_agreement_version_precedes_invalid_mfn_state(
        self, api, affiliate_sales_exec_headers
    ):
        """PRD §2.7: "`POST /carriage/mfn-clauses/{mfnClauseId}/reset` also requires
        `expected_agreement_version`, matched against the current `version` of the
        agreement named by the clause's `agreement_id`; a mismatch yields
        `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."
        PRD §2.8: "8. Optimistic-concurrency match on `expected_agreement_version`
        or `expected_distributor_version` (rule 20)."
        PRD §2.8: "9. Own-entity state admissibility (rules 30 through 37):
        agreement lifecycle, agreement renewal, report review, engagement, rights
        window, invoice, blackout rule and MFN clause, each with its own conflict
        code."

        Design: Difficulty/priority_pair_validation_conflict/stale_agreement_version_precedes_invalid_mfn_state
        """
        _distributor, _agreement, clause = _setup_agreement_with_waived_mfn_clause()
        assert clause["status"] == "WAIVED", (
            f"the clause must already be waived before the trigger, got {clause['status']}"
        )

        validate_error(
            api.reset_mfn_clause(
                clause["id"],
                {"action": "RESET", "expected_agreement_version": 999},
                affiliate_sales_exec_headers,
            ),
            "ERR_STALE_AGREEMENT_VERSION",
            412,
        )

        unchanged = validate_success(
            api.get_mfn_clause(clause["id"], affiliate_sales_exec_headers), 200
        )
        assert unchanged["status"] == "WAIVED", (
            f"the rejected reset must change nothing, got status {unchanged['status']}"
        )
        assert unchanged["benchmark_status"] == "NOT_EVALUATED", (
            f"the rejected reset must not benchmark, got {unchanged['benchmark_status']}"
        )
        assert unchanged["benchmark_rate_cents"] is None, (
            f"the rejected reset must leave the benchmark null, got {unchanged['benchmark_rate_cents']}"
        )

    def test_reset_with_the_current_version_then_surfaces_invalid_mfn_state(
        self, api, affiliate_sales_exec_headers
    ):
        """PRD §3.3: "Re-running the benchmark is an explicit act by an
        `AffiliateSalesExec`, guarded by `expected_agreement_version` as described in
        §2.7, and available only while the clause is `ACTIVE` — a reset or waiver
        aimed at a clause that is already `WAIVED` is refused with
        `ERR_INVALID_MFN_STATE`."
        PRD §2.8: "9. Own-entity state admissibility (rules 30 through 37):
        agreement lifecycle, agreement renewal, report review, engagement, rights
        window, invoice, blackout rule and MFN clause, each with its own conflict
        code."

        Design: Difficulty/priority_pair_validation_conflict/stale_agreement_version_precedes_invalid_mfn_state
        """
        _distributor, agreement, clause = _setup_agreement_with_waived_mfn_clause()

        validate_error(
            api.reset_mfn_clause(
                clause["id"],
                {
                    "action": "RESET",
                    "expected_agreement_version": agreement_version(agreement["id"]),
                },
                affiliate_sales_exec_headers,
            ),
            "ERR_INVALID_MFN_STATE",
            409,
        )


def _setup_operator_at_the_monthly_blackout_cap():
    """Northgate holds two scheduled US blackouts in September 2026 — a 48-hour
    rule and a 24-hour rule clear of its buffer — which together consume exactly
    the 72-hour monthly cap.

    Returns (agreement, first_rule, second_rule).
    """
    _distributor, agreement = setup_executed_agreement(
        NORTHGATE_OPERATOR, dict(NORTHGATE_TERMS)
    )
    first = schedule_blackout(
        agreement["id"],
        territory_code="US",
        blackout_start="2026-09-01T00:00:00Z",
        blackout_end="2026-09-03T00:00:00Z",
        substitution_required=False,
    )
    second = schedule_blackout(
        agreement["id"],
        territory_code="US",
        blackout_start="2026-09-05T00:00:00Z",
        blackout_end="2026-09-06T00:00:00Z",
        substitution_required=False,
    )
    return agreement, first, second


class TestBlackoutSeparationBeforeMonthlyCap:
    """The pairwise separation rule is evaluated before the aggregate monthly
    hour cap on the same endpoint."""

    def test_separation_violation_precedes_monthly_cap_exceeded(
        self, api, rights_administrator_headers
    ):
        """PRD §3.6: "The rule's own `blackout_hours` is the elapsed time from
        `blackout_start` to `blackout_end` expressed in hours and rounded half up to
        two decimal places."
        PRD §3.6: "The separation check comes first: applying the closed-interval
        convention and the 24-hour buffer of §2.10, a proposed rule that comes within
        a day of an existing rule on the same key — including touching it exactly —
        is refused with `ERR_BLACKOUT_SEPARATION_VIOLATION`."
        PRD §3.6: "The monthly cap comes second."
        PRD §2.10: "Two blackouts on the same key conflict when each one's start,
        pulled back by the buffer, is at or before the other's end — so adjacency is
        illegal here, and a gap of zero hours, or even of 23 hours, is refused where
        the window resource would have accepted it."

        Design: Difficulty/priority_pair_validation_conflict/blackout_separation_precedes_monthly_cap
        """
        agreement, first, second = _setup_operator_at_the_monthly_blackout_cap()
        assert first["blackout_hours"] == pytest.approx(48.00, abs=0.01), (
            f"2026-09-01 to 2026-09-03 is 48.00 hours, got {first['blackout_hours']}"
        )
        assert first["monthly_blackout_hours"] == pytest.approx(48.00, abs=0.01), (
            f"the first rule alone totals 48.00 hours, got {first['monthly_blackout_hours']}"
        )
        assert second["monthly_blackout_hours"] == pytest.approx(72.00, abs=0.01), (
            "48.00 plus 24.00 hours consumes the cap exactly, got "
            f"{second['monthly_blackout_hours']}"
        )

        validate_error(
            api.create_blackout_rule(
                {
                    "agreement_id": agreement["id"],
                    "territory_code": "US",
                    "blackout_start": "2026-09-03T12:00:00Z",
                    "blackout_end": "2026-09-04T12:00:00Z",
                    "substitution_required": False,
                },
                rights_administrator_headers,
            ),
            "ERR_BLACKOUT_SEPARATION_VIOLATION",
            409,
        )

        rows, meta = validate_paginated(
            api.list_blackout_rules(
                rights_administrator_headers, params={"agreement_id": agreement["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"the refused rule must not be persisted, got total_count {meta['total_count']}"
        )
        assert len(rows) == 2, f"expected exactly the two scheduled rules, got {len(rows)}"

    def test_rule_clear_of_every_buffer_still_hits_the_monthly_cap(
        self, api, rights_administrator_headers
    ):
        """PRD §3.6: "`monthly_blackout_hours` is that figure plus the
        `blackout_hours` of every other qualifying rule on the same key whose
        `blackout_start` falls in the same UTC calendar month, and if the total
        exceeds 72 hours — three full days of blackout in one operator territory in
        one month — the rule is refused with `ERR_BLACKOUT_MONTHLY_CAP_EXCEEDED`."
        PRD §2.10: "Two blackouts on the same key conflict when each one's start,
        pulled back by the buffer, is at or before the other's end — so adjacency is
        illegal here, and a gap of zero hours, or even of 23 hours, is refused where
        the window resource would have accepted it."

        Design: Difficulty/priority_pair_validation_conflict/blackout_separation_precedes_monthly_cap
        """
        agreement, _first, _second = _setup_operator_at_the_monthly_blackout_cap()

        validate_error(
            api.create_blackout_rule(
                {
                    "agreement_id": agreement["id"],
                    "territory_code": "US",
                    "blackout_start": "2026-09-20T00:00:00Z",
                    "blackout_end": "2026-09-21T00:00:00Z",
                    "substitution_required": False,
                },
                rights_administrator_headers,
            ),
            "ERR_BLACKOUT_MONTHLY_CAP_EXCEEDED",
            422,
        )


CLIFFSIDE_OPERATOR = {
    "legal_name": "Cliffside Telco",
    "distributor_type": "TELCO",
    "rate_card_class": "CLASS_B",
    "total_subscribers": 200_000,
    "credit_limit_cents": 100_000_000,
}

CLIFFSIDE_TERMS = {
    "contract_code": "CT-2025-01",
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
    "launch_fee_cents": 0,
    "marketing_commitment_cents": 0,
}


def _setup_cliffside_submitted_report(reported_subscribers):
    """Cliffside Telco carries 200,000 video subscribers under a flat 40.0000
    BASIC agreement with a 50% penetration floor, so the enforceable floor is
    100,000 subscribers, and files one 2026-06 report at the given count.

    Returns (distributor, agreement, report).
    """
    distributor = register_distributor(**CLIFFSIDE_OPERATOR)
    agreement = draft_agreement(distributor["id"], **CLIFFSIDE_TERMS)
    agreement = execute_agreement(agreement["id"])
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=reported_subscribers,
        reported_tier="BASIC",
    )
    return distributor, agreement, report


class TestPenetrationFloorInclusiveBoundary:
    """The penetration comparison is inclusive and happens at four decimal
    places, while the billable count is decided by a different comparison."""

    def test_exactly_on_the_floor_is_compliant(self, api, revenue_accountant_headers):
        """PRD §3.5: "The comparison is **inclusive**: the period is compliant when
        the report's `penetration_pct` is greater than or equal to the agreement's
        `penetration_floor_pct`, with both values rounded to four decimal places
        before being compared, so an operator that lands exactly on its floor is
        compliant."
        PRD §3.5: "A compliant period increments `consecutive_compliant_periods` by
        one and sets `penetration_compliance_status` to `COMPLIANT`."
        PRD §3.4: "`penetration_pct` is `reported_subscribers` divided by the
        operator's `total_subscribers`, rounded half up to four decimal places."

        Design: Difficulty/boundary_precision_check/penetration_floor_inclusive_at_exact_threshold
        """
        _distributor, agreement, report = _setup_cliffside_submitted_report(100_000)

        accepted = validate_success(
            api.review_subscriber_report(
                report["id"], {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            200,
        )
        assert accepted["penetration_pct"] == pytest.approx(0.5000, abs=1e-6), (
            f"100,000 of 200,000 is 0.5000, got {accepted['penetration_pct']}"
        )
        assert accepted["billable_subscribers"] == 100_000, (
            f"expected billable 100000, got {accepted['billable_subscribers']}"
        )
        assert accepted["license_fee_due_cents"] == 4_000_000, (
            f"100,000 * 40.0000 * 1.00 is 4000000 cents, got {accepted['license_fee_due_cents']}"
        )

        after = fetch_agreement(agreement["id"])
        assert after["penetration_compliance_status"] == "COMPLIANT", (
            "landing exactly on the floor is compliant, got "
            f"{after['penetration_compliance_status']}"
        )
        assert after["penetration_breach_count"] == 0, (
            f"expected no breach on the boundary, got {after['penetration_breach_count']}"
        )
        assert after["consecutive_compliant_periods"] == 1, (
            f"expected a compliant run of 1, got {after['consecutive_compliant_periods']}"
        )
        assert after["lifecycle_status"] == "EXECUTED", (
            f"a compliant period suspends nothing, got {after['lifecycle_status']}"
        )

    def test_one_subscriber_short_still_rounds_onto_the_floor(
        self, api, revenue_accountant_headers
    ):
        """PRD §2.6: "penetration is carried to four decimal places, and both sides
        of a penetration comparison are rounded to four decimal places before being
        compared"
        PRD §3.5: "The comparison is **inclusive**: the period is compliant when
        the report's `penetration_pct` is greater than or equal to the agreement's
        `penetration_floor_pct`, with both values rounded to four decimal places
        before being compared, so an operator that lands exactly on its floor is
        compliant."
        PRD §3.4: "Under the **final** variant, stamped at acceptance into
        `billable_subscribers` and `license_fee_due_cents`, the billable count is the
        greater of `reported_subscribers` and the floor subscriber count."

        Design: Difficulty/boundary_precision_check/penetration_floor_inclusive_at_exact_threshold
        """
        _distributor, agreement, report = _setup_cliffside_submitted_report(99_999)

        accepted = validate_success(
            api.review_subscriber_report(
                report["id"], {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            200,
        )
        assert accepted["penetration_pct"] == pytest.approx(0.5000, abs=1e-6), (
            "99,999 of 200,000 is 0.499995, which rounds half up to 0.5000, got "
            f"{accepted['penetration_pct']}"
        )
        assert accepted["billable_subscribers"] == 100_000, (
            f"the floor count still bills, got {accepted['billable_subscribers']}"
        )
        assert accepted["license_fee_due_cents"] == 4_000_000, (
            f"expected 4000000 cents, got {accepted['license_fee_due_cents']}"
        )

        after = fetch_agreement(agreement["id"])
        assert after["penetration_compliance_status"] == "COMPLIANT", (
            "a raw ratio below the floor that rounds onto it is compliant, got "
            f"{after['penetration_compliance_status']}"
        )
        assert after["penetration_breach_count"] == 0, (
            f"expected no breach, got {after['penetration_breach_count']}"
        )

    def test_a_thousand_short_flips_the_period_into_breach(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.5: "A non-compliant period does the reverse.
        `consecutive_compliant_periods` drops to 0, `penetration_breach_count`
        increments by one, and `penetration_compliance_status` becomes `BREACH`."
        PRD §3.4: "Under the **final** variant, stamped at acceptance into
        `billable_subscribers` and `license_fee_due_cents`, the billable count is the
        greater of `reported_subscribers` and the floor subscriber count."
        PRD §3.4: "Whenever the operator reported fewer subscribers than the floor
        requires, the final fee therefore strictly exceeds the provisional fee for
        identical inputs — the network bills the floor it negotiated, not the
        shortfall the operator delivered."

        Design: Difficulty/boundary_precision_check/penetration_floor_inclusive_at_exact_threshold
        """
        _distributor, agreement, report = _setup_cliffside_submitted_report(99_000)

        accepted = validate_success(
            api.review_subscriber_report(
                report["id"], {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            200,
        )
        assert accepted["penetration_pct"] == pytest.approx(0.4950, abs=1e-6), (
            f"99,000 of 200,000 is 0.4950, got {accepted['penetration_pct']}"
        )
        assert accepted["license_fee_due_cents"] == 4_000_000, (
            "the fee is identical to the compliant cases because the floor bills, got "
            f"{accepted['license_fee_due_cents']}"
        )

        after = fetch_agreement(agreement["id"])
        assert after["penetration_compliance_status"] == "BREACH", (
            f"0.4950 is below the 0.50 floor, got {after['penetration_compliance_status']}"
        )
        assert after["penetration_breach_count"] == 1, (
            f"expected the breach ladder to start, got {after['penetration_breach_count']}"
        )
        assert after["consecutive_compliant_periods"] == 0, (
            f"expected the compliant run destroyed, got {after['consecutive_compliant_periods']}"
        )


HARBOR_OPERATOR = {
    "legal_name": "Harbor Point Cable",
    "distributor_type": "CABLE_MSO",
    "rate_card_class": "CLASS_C",
    "total_subscribers": 400_000,
    "credit_limit_cents": 150_000_000,
}

HARBOR_TERMS = {
    "contract_code": "HP-2025-01",
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.40,
    "committed_tier": "BASIC",
    "launch_fee_cents": 0,
    "marketing_commitment_cents": 0,
}

HARBOR_JUNE_REPORT = {
    "period_month": "2026-06",
    "reported_subscribers": 200_000,
    "reported_tier": "BASIC",
}


def _setup_harbor_engagement_with_one_finding(audited_subscribers):
    """Harbor Point's accepted 2026-06 month of 200,000 subscribers, under audit
    on the period rate, with a single finding at the given audited count.

    Returns (agreement, report, engagement, finding).
    """
    _distributor, agreement, report, engagement = setup_engagement_in_fieldwork(
        HARBOR_OPERATOR,
        dict(HARBOR_TERMS),
        dict(HARBOR_JUNE_REPORT),
        {
            "sample_period_start": "2026-06",
            "sample_period_end": "2026-06",
            "rate_basis": "PERIOD_RATE",
        },
    )
    finding = record_finding(engagement["id"], report["id"], audited_subscribers)
    return agreement, report, engagement, finding


class TestUnderreportingPenaltyInclusiveBoundary:
    """The penalty step and the flat audit-cost shift both trip at exactly
    0.0500, and the cost shift is added outside the multiplication."""

    def test_five_percent_exactly_trips_penalty_and_cost_shift(
        self, api, audit_manager_headers
    ):
        """PRD §3.7: "`underreporting_pct` is `total_variance_subscribers` divided by
        `total_reported_subscribers`, rounded half up to four decimal places, and is
        exactly 0 when the denominator is 0."
        PRD §3.7: "`penalty_multiplier` is then selected from `underreporting_pct` by
        a ladder with inclusive lower bounds: 1.00 below 0.0500, 1.10 from 0.0500 up
        to but not including 0.1000, and 1.25 at 0.1000 and above."
        PRD §3.7: "Separately, `audit_cost_shift_cents` is 2,500,000 cents — the
        network's flat 25,000-dollar cost of audit, shifted onto the operator —
        whenever `underreporting_pct` is at least 0.0500, and 0 otherwise; the shift
        threshold and the first penalty step deliberately coincide."
        PRD §3.7: "Finally, `recovery_amount_cents` is the sum of the base total and
        the interest total, multiplied by `penalty_multiplier` and rounded half up to
        a whole cent, and then the `audit_cost_shift_cents` is added on top — the cost
        shift is never itself penalty-multiplied."

        Design: Difficulty/boundary_precision_check/underreporting_penalty_threshold_inclusive_at_five_percent
        """
        _agreement, report, engagement, finding = _setup_harbor_engagement_with_one_finding(
            210_000
        )
        assert report["license_fee_due_cents"] == 8_000_000, (
            f"200,000 * 40.0000 * 1.00 is 8000000 cents, got {report['license_fee_due_cents']}"
        )
        assert finding["variance_subscribers"] == 10_000, (
            f"210,000 audited less 200,000 reported is 10000, got {finding['variance_subscribers']}"
        )

        issued = validate_success(
            api.audit_engagement_lifecycle(
                engagement["id"], {"action": "ISSUE_FINDINGS"}, audit_manager_headers
            ),
            200,
        )
        assert issued["total_variance_subscribers"] == 10_000, (
            f"expected accumulated variance 10000, got {issued['total_variance_subscribers']}"
        )
        assert issued["total_reported_subscribers"] == 200_000, (
            f"expected accumulated reported 200000, got {issued['total_reported_subscribers']}"
        )
        assert issued["underreporting_pct"] == pytest.approx(0.0500, abs=1e-6), (
            f"10,000 of 200,000 is 0.0500, got {issued['underreporting_pct']}"
        )
        assert issued["penalty_multiplier"] == pytest.approx(1.10, abs=1e-6), (
            f"0.0500 sits on the inclusive 1.10 step, got {issued['penalty_multiplier']}"
        )
        assert issued["audit_cost_shift_cents"] == 2_500_000, (
            f"the flat cost shift applies at 0.0500, got {issued['audit_cost_shift_cents']}"
        )
        assert issued["base_recovery_cents"] == 400_000, (
            f"10,000 * 40.0000 * 1.00 is 400000 cents, got {issued['base_recovery_cents']}"
        )
        assert issued["interest_cents"] == 3_000, (
            f"400,000 * 0.0075 for one whole month is 3000, got {issued['interest_cents']}"
        )
        assert issued["recovery_amount_cents"] == 2_943_300, (
            "round(403000 * 1.10) plus the 2500000 shift is 2943300, got "
            f"{issued['recovery_amount_cents']}"
        )
        assert issued["recovery_amount_cents"] != 3_187_300, (
            "the cost shift must not itself be penalty-multiplied, got "
            f"{issued['recovery_amount_cents']}"
        )

    def test_just_under_five_percent_carries_no_penalty_or_cost_shift(
        self, api, audit_manager_headers
    ):
        """PRD §3.7: "`penalty_multiplier` is then selected from `underreporting_pct`
        by a ladder with inclusive lower bounds: 1.00 below 0.0500, 1.10 from 0.0500
        up to but not including 0.1000, and 1.25 at 0.1000 and above."
        PRD §3.7: "Separately, `audit_cost_shift_cents` is 2,500,000 cents — the
        network's flat 25,000-dollar cost of audit, shifted onto the operator —
        whenever `underreporting_pct` is at least 0.0500, and 0 otherwise; the shift
        threshold and the first penalty step deliberately coincide."
        PRD §3.7: "Count the whole calendar months from the **last day of the
        finding's `period_month`** to the current logical instant, treating any
        negative count as zero, and multiply `finding_recovery_cents` by 0.0075 —
        three quarters of one percent per month, simple, not compounding — and by that
        month count, rounding half up to a whole cent."

        Design: Difficulty/boundary_precision_check/underreporting_penalty_threshold_inclusive_at_five_percent
        """
        _agreement, _report, engagement, finding = _setup_harbor_engagement_with_one_finding(
            209_900
        )
        assert finding["variance_subscribers"] == 9_900, (
            f"209,900 audited less 200,000 reported is 9900, got {finding['variance_subscribers']}"
        )

        issued = validate_success(
            api.audit_engagement_lifecycle(
                engagement["id"], {"action": "ISSUE_FINDINGS"}, audit_manager_headers
            ),
            200,
        )
        assert issued["underreporting_pct"] == pytest.approx(0.0495, abs=1e-6), (
            f"9,900 of 200,000 is 0.0495, got {issued['underreporting_pct']}"
        )
        assert issued["penalty_multiplier"] == pytest.approx(1.00, abs=1e-6), (
            f"0.0495 is below the first step, got {issued['penalty_multiplier']}"
        )
        assert issued["audit_cost_shift_cents"] == 0, (
            f"no cost shift below 0.0500, got {issued['audit_cost_shift_cents']}"
        )
        assert issued["base_recovery_cents"] == 396_000, (
            f"9,900 * 40.0000 * 1.00 is 396000 cents, got {issued['base_recovery_cents']}"
        )
        assert issued["interest_cents"] == 2_970, (
            f"396,000 * 0.0075 for one whole month is 2970, got {issued['interest_cents']}"
        )
        assert issued["recovery_amount_cents"] == 398_970, (
            f"398970 is 396000 plus 2970 unmultiplied, got {issued['recovery_amount_cents']}"
        )


RIDGEWAY_OPERATOR = {
    "legal_name": "Ridgeway Cable Cooperative",
    "distributor_type": "CABLE_MSO",
    "rate_card_class": "CLASS_C",
    "total_subscribers": 2_000,
    "credit_limit_cents": 5_000_000,
}

RIDGEWAY_TERMS = {
    "contract_code": "RC-2025-01",
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2028-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0005,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
    "launch_fee_cents": 0,
    "marketing_commitment_cents": 0,
}


def _setup_ridgeway_half_cent_report():
    """Ridgeway prices at 40.0005 cents per subscriber and reports exactly 1,000
    subscribers, so the monthly product is exactly 40000.5 cents.

    Returns (agreement, report).
    """
    distributor = register_distributor(**RIDGEWAY_OPERATOR)
    agreement = draft_agreement(distributor["id"], **RIDGEWAY_TERMS)
    agreement = execute_agreement(agreement["id"])
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=1_000,
        reported_tier="BASIC",
    )
    return agreement, report


class TestHalfCentRoundsHalfUp:
    """A licence fee landing on exactly half a cent rounds up, and the four
    decimal places of the rate survive to the multiplication."""

    def test_submission_stamps_the_provisional_half_cent_upward(self):
        """PRD §3.3: "The escalated rate is then `base_license_fee_cents_per_sub`
        multiplied by one plus `escalator_pct`, raised to the power of that
        contract-year index, rounded half up to four decimal places of a cent."
        PRD §3.4: "Under the **provisional** variant, stamped at submission into
        `provisional_fee_cents`, the billable count is `reported_subscribers`
        verbatim; the penetration floor is ignored entirely."
        PRD §3.4: "The fee is the billable subscriber count multiplied by
        `rate_applied_cents_per_sub` multiplied by that tier multiplier, rounded half
        up to a whole number of cents."

        Design: Difficulty/boundary_precision_check/license_fee_half_cent_rounds_half_up
        """
        agreement, report = _setup_ridgeway_half_cent_report()

        assert agreement["effective_rate_cents_per_sub"] == pytest.approx(
            40.0005, abs=1e-6
        ), (
            "a flat agreement stamps its base rate at four decimals, got "
            f"{agreement['effective_rate_cents_per_sub']}"
        )
        assert report["provisional_fee_cents"] == 40_001, (
            "1,000 * 40.0005 * 1.00 is exactly 40000.5, which rounds half up to 40001, got "
            f"{report['provisional_fee_cents']}"
        )
        assert report["provisional_fee_cents"] != 40_000, (
            "rounding half to even would answer 40000, got "
            f"{report['provisional_fee_cents']}"
        )

    def test_acceptance_stamps_the_final_half_cent_upward(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.4: "The fee is the billable subscriber count multiplied by
        `rate_applied_cents_per_sub` multiplied by that tier multiplier, rounded half
        up to a whole number of cents."
        PRD §3.4: "Because each report's fee is rounded to whole cents at this
        point, and invoices later sum those already-rounded integers, the report is
        the unit of rounding."
        PRD §3.4: "First, the agreement's `recognized_revenue_cents` increases by the
        newly stamped `license_fee_due_cents`, and `penetration_compliance_status` is
        re-derived as described in §3.5."

        Design: Difficulty/boundary_precision_check/license_fee_half_cent_rounds_half_up
        """
        agreement, report = _setup_ridgeway_half_cent_report()

        accepted = validate_success(
            api.review_subscriber_report(
                report["id"], {"action": "ACCEPT"}, revenue_accountant_headers
            ),
            200,
        )
        assert accepted["rate_applied_cents_per_sub"] == pytest.approx(40.0005, abs=1e-6), (
            "the four-decimal rate must survive to the multiplication, got "
            f"{accepted['rate_applied_cents_per_sub']}"
        )
        assert accepted["billable_subscribers"] == 1_000, (
            f"the floor count is also 1000, got {accepted['billable_subscribers']}"
        )
        assert accepted["penetration_pct"] == pytest.approx(0.5000, abs=1e-6), (
            f"1,000 of 2,000 is 0.5000, got {accepted['penetration_pct']}"
        )
        assert accepted["license_fee_due_cents"] == 40_001, (
            f"40000.5 cents rounds half up to 40001, got {accepted['license_fee_due_cents']}"
        )
        assert accepted["license_fee_due_cents"] != 40_000, (
            "truncation or half-to-even would answer 40000, got "
            f"{accepted['license_fee_due_cents']}"
        )

        after = fetch_agreement(agreement["id"])
        assert after["recognized_revenue_cents"] == 40_001, (
            "recognised revenue takes the already-rounded report figure, got "
            f"{after['recognized_revenue_cents']}"
        )


def _setup_cliffside_billable_month(reported_subscribers):
    """Cliffside with a 1,000,000-cent co-op line half earned and nothing billed,
    and an accepted 2026-06 report at the given subscriber count.

    Returns (distributor, agreement, commitment, accepted_report).
    """
    distributor = register_distributor(**CLIFFSIDE_OPERATOR)
    agreement = draft_agreement(distributor["id"], **CLIFFSIDE_TERMS)
    agreement = execute_agreement(agreement["id"])
    commitment = create_commitment(
        agreement["id"],
        commitment_type="COOP_ADVERTISING",
        committed_cents=1_000_000,
        performance_deadline="2026-12-31T00:00:00Z",
    )
    earn_commitment(commitment["id"], 500_000, "COOP-Q2-2026-INSERTION-ORDER")
    report = file_report(
        agreement["id"],
        distributor["id"],
        period_month="2026-06",
        reported_subscribers=reported_subscribers,
        reported_tier="BASIC",
    )
    report = accept_report(report["id"])
    return distributor, agreement, commitment, report


class TestCoopBandInclusiveLowerBound:
    """The co-op ceiling band is selected from the step-1 gross with inclusive
    lower bounds, so exactly 5,000,000 cents belongs to the 0.08 band."""

    def test_gross_of_exactly_five_million_selects_the_eight_percent_band(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.8: "For a `LICENSE_FEE` invoice, `gross_license_fee_cents` is the
        sum of `license_fee_due_cents` over the subscriber reports of the named
        agreement whose `period_month` equals the invoice's `period_month`, whose
        `status` is `ACCEPTED` or `AUDIT_ADJUSTED`, and whose `invoice_id` is still
        null — each of those figures already rounded per report."
        PRD §3.8: "`coop_cap_pct` is selected from that gross: 0.05 when the gross is
        below 5,000,000 cents, 0.08 from 5,000,000 cents up to but not including
        25,000,000 cents, and 0.12 at 25,000,000 cents and above."
        PRD §3.8: "The ceiling itself is the gross multiplied by `coop_cap_pct`,
        rounded half up to a whole cent — the only rounded intermediate in the
        waterfall."
        PRD §3.8: "`coop_offset_cents` is the lesser of that pool and the step-2
        ceiling."
        PRD §3.8: "The raw net is the gross less `coop_offset_cents` less
        `launch_fee_offset_cents` plus `recovery_adjustment_cents`."

        Design: Difficulty/boundary_precision_check/coop_band_lower_bound_inclusive_at_five_million_gross
        """
        distributor, agreement, commitment, report = _setup_cliffside_billable_month(
            125_000
        )
        assert report["license_fee_due_cents"] == 5_000_000, (
            f"125,000 * 40.0000 * 1.00 is 5000000 cents, got {report['license_fee_due_cents']}"
        )

        drafted = validate_success(
            api.create_invoice(
                create_invoice_payload(
                    distributor["id"],
                    agreement["id"],
                    "2026-06",
                    distributor_version(distributor["id"]),
                ),
                revenue_accountant_headers,
            ),
            201,
        )
        assert drafted["gross_license_fee_cents"] == 5_000_000, (
            f"expected gross 5000000, got {drafted['gross_license_fee_cents']}"
        )
        assert drafted["coop_cap_pct"] == pytest.approx(0.08, abs=1e-6), (
            f"5,000,000 is the inclusive lower bound of the 0.08 band, got {drafted['coop_cap_pct']}"
        )
        assert drafted["coop_cap_pct"] != pytest.approx(0.05, abs=1e-6), (
            f"an exclusive comparison would answer 0.05, got {drafted['coop_cap_pct']}"
        )
        assert drafted["coop_offset_cents"] == 400_000, (
            "the 500,000 pool exceeds the 400,000 ceiling, so the ceiling decides, got "
            f"{drafted['coop_offset_cents']}"
        )
        assert drafted["coop_offset_cents"] != 250_000, (
            f"250000 would be the 0.05 ceiling, got {drafted['coop_offset_cents']}"
        )
        assert drafted["net_due_cents"] == 4_600_000, (
            f"5,000,000 less 400,000 is 4600000, got {drafted['net_due_cents']}"
        )

        line = fetch_commitment(commitment["id"])
        assert line["billed_cents"] == 0, (
            f"a draft only projects its offsets, got billed_cents {line['billed_cents']}"
        )
        assert line["earned_unbilled_cents"] == 500_000, (
            "the earned-unbilled pool is untouched at drafting, got "
            f"{line['earned_unbilled_cents']}"
        )

    def test_one_subscriber_less_drops_into_the_five_percent_band(
        self, api, revenue_accountant_headers
    ):
        """PRD §3.8: "`coop_cap_pct` is selected from that gross: 0.05 when the gross
        is below 5,000,000 cents, 0.08 from 5,000,000 cents up to but not including
        25,000,000 cents, and 0.12 at 25,000,000 cents and above."
        PRD §3.8: "The ceiling itself is the gross multiplied by `coop_cap_pct`,
        rounded half up to a whole cent — the only rounded intermediate in the
        waterfall."
        PRD §3.8: "Voiding a `DRAFT` restores nothing, and that is the point: a draft
        only *projects* its offsets, so `billed_cents` and `earned_unbilled_cents` were
        never touched at drafting and are not touched at void, and the conserved
        identity of §3.8 holds unchanged across both calls."

        Design: Difficulty/boundary_precision_check/coop_band_lower_bound_inclusive_at_five_million_gross
        """
        distributor, agreement, commitment, report = _setup_cliffside_billable_month(
            124_999
        )
        assert report["license_fee_due_cents"] == 4_999_960, (
            f"124,999 * 40.0000 * 1.00 is 4999960 cents, got {report['license_fee_due_cents']}"
        )

        drafted = validate_success(
            api.create_invoice(
                create_invoice_payload(
                    distributor["id"],
                    agreement["id"],
                    "2026-06",
                    distributor_version(distributor["id"]),
                ),
                revenue_accountant_headers,
            ),
            201,
        )
        assert drafted["gross_license_fee_cents"] == 4_999_960, (
            f"expected gross 4999960, got {drafted['gross_license_fee_cents']}"
        )
        assert drafted["coop_cap_pct"] == pytest.approx(0.05, abs=1e-6), (
            f"40 cents below the band boundary is 0.05, got {drafted['coop_cap_pct']}"
        )
        assert drafted["coop_offset_cents"] == 249_998, (
            f"4,999,960 * 0.05 is 249998, got {drafted['coop_offset_cents']}"
        )
        assert drafted["net_due_cents"] == 4_749_962, (
            "40 cents less gross leaves the operator owing more, got "
            f"{drafted['net_due_cents']}"
        )

        line = fetch_commitment(commitment["id"])
        assert line["earned_unbilled_cents"] == 500_000, (
            f"drafting reserves nothing, got {line['earned_unbilled_cents']}"
        )
