"""Engagements, fee applications, fee cap, EXHAUSTED auto-transition."""
from test_helpers import (
    COURT,
    RECEIVER,
    ApiErrorId,
    create_approved_engagement,
    create_case,
    create_engagement,
    create_fee_application,
    decide_engagement,
    decide_fee_application,
    get_case,
    pay_fee_application,
    setup_case_with_cash,
    validate_error,
    validate_success,
)


class TestEngagementCreation:
    def test_engagement_hourly_missing_rate_returns_400(self, api):
        """PRD §3.5: "An `HOURLY` engagement must supply its default
        `hourly_rate_cents` and must not supply `contingency_pct`; a
        `CONTINGENT` engagement must supply `contingency_pct` — the fraction
        of the recovery charged, such as 0.10 — and must not supply
        `hourly_rate_cents`."

        Design: Corner/entities/engagement_hourly_missing_rate_returns_400
        """
        case = create_case()
        resp1 = api.create_engagement(
            {
                "case_id": case["id"],
                "professional_name": "L. Lawyer",
                "firm_name": "Law LLP",
                "role_type": "COUNSEL",
                "fee_arrangement": "HOURLY",
                "fee_cap_cents": 1000000,
            },
            RECEIVER,
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

        resp2 = api.create_engagement(
            {
                "case_id": case["id"],
                "professional_name": "A. Accountant",
                "firm_name": "Acct LLC",
                "role_type": "ACCOUNTANT",
                "fee_arrangement": "CONTINGENT",
                "contingency_pct": 0.10,
                "hourly_rate_cents": 20000,
                "fee_cap_cents": 1000000,
            },
            RECEIVER,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    def test_second_same_role_engagement_rejected(self, api):
        """PRD §3.5: "One professional per discipline is the rule: a second
        engagement on the same case with the same `role_type` while one is
        `PROPOSED` or `APPROVED` is rejected with
        `ERR_ENGAGEMENT_ALREADY_ACTIVE`."

        Design: Corner/validations/second_same_role_engagement_rejected
        """
        case = create_case()
        create_engagement(case["id"], professional_name="L. Lawyer", role_type="COUNSEL")

        resp = api.create_engagement(
            {
                "case_id": case["id"],
                "professional_name": "M. Morelaw",
                "firm_name": "More Law PC",
                "role_type": "COUNSEL",
                "fee_arrangement": "HOURLY",
                "hourly_rate_cents": 25000,
                "fee_cap_cents": 1000000,
            },
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_ALREADY_ACTIVE)

        other = api.create_engagement(
            {
                "case_id": case["id"],
                "professional_name": "A. Accountant",
                "firm_name": "Acct LLC",
                "role_type": "ACCOUNTANT",
                "fee_arrangement": "HOURLY",
                "hourly_rate_cents": 15000,
                "fee_cap_cents": 1000000,
            },
            RECEIVER,
        )
        assert validate_success(other, 201)["status"] == "PROPOSED", (
            "different role_type is permitted"
        )


class TestEngagementDecide:
    def test_decide_on_decided_engagement_returns_invalid_state(self, api):
        """PRD §2.10: "From-state validity of the requested transition —
        liquidation requires an `IDENTIFIED` asset, a decision requires the
        instrument's pending state, a fee payment requires an `APPROVED`
        application, a distribution payment requires a `SCHEDULED` payment,
        discharge requires a `DISTRIBUTING` case — else `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/decide_on_decided_engagement_returns_invalid_state
        """
        case = create_case()
        eng = create_engagement(case["id"])
        decide_engagement(eng["id"], "APPROVE")

        resp = api.decide_engagement(eng["id"], {"decision": "APPROVE"}, COURT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFeeApplicationGates:
    def test_fee_application_requires_approved_engagement(self, api):
        """PRD §3.5: "Against an `APPROVED` engagement — and only an
        `APPROVED` one, with filings against a `PROPOSED`, `DENIED`,
        `EXHAUSTED`, or `CLOSED` engagement rejected with
        `ERR_ENGAGEMENT_NOT_APPROVED` — the receiver files fee applications."

        Design: Difficulty/cross_entity_state_dependency/fee_application_requires_approved_engagement
        """
        case = create_case()
        eng = create_engagement(case["id"])  # PROPOSED

        payload = {
            "engagement_id": eng["id"],
            "period_start": "2026-08-01T00:00:00Z",
            "period_end": "2026-08-31T00:00:00Z",
            "time_entries": [{"hours": 1.0, "rate_cents": 20000}],
            "expenses_cents": 0,
        }
        resp = api.create_fee_application(payload, RECEIVER)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_APPROVED)

        decide_engagement(eng["id"], "APPROVE")
        resp2 = api.create_fee_application(payload, RECEIVER)
        assert validate_success(resp2, 201)["status"] == "FILED"

    def test_fee_application_on_denied_engagement_rejected(self, api):
        """PRD §3.5: "Against an `APPROVED` engagement — and only an
        `APPROVED` one, with filings against a `PROPOSED`, `DENIED`,
        `EXHAUSTED`, or `CLOSED` engagement rejected with
        `ERR_ENGAGEMENT_NOT_APPROVED` — the receiver files fee applications."

        Design: Difficulty/cross_entity_state_dependency/fee_application_requires_approved_engagement
        """
        case = create_case()
        eng = create_engagement(case["id"])
        decide_engagement(eng["id"], "REJECT")  # DENIED

        resp = api.create_fee_application(
            {
                "engagement_id": eng["id"],
                "period_start": "2026-08-01T00:00:00Z",
                "period_end": "2026-08-31T00:00:00Z",
                "time_entries": [{"hours": 1.0, "rate_cents": 20000}],
                "expenses_cents": 0,
            },
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_APPROVED)


class TestFeePeriodOverlap:
    def test_fee_application_period_overlap_half_open(self, api):
        """PRD §3.5: "Each application names its `engagement_id` and covers
        a half-open period from `period_start` (inclusive) to `period_end`
        (exclusive), with `period_start` strictly before `period_end`; the
        periods of non-`DENIED` applications on the same engagement must not
        overlap, failing with `ERR_FEE_PERIOD_OVERLAP`, though gaps and
        abutting periods are permitted."

        Design: Difficulty/resource_temporal_overlap/fee_application_period_overlap_half_open
        """
        case = create_case()
        eng = create_approved_engagement(case["id"], fee_cap_cents=5000000)
        first = create_fee_application(
            eng["id"], period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            time_entries=[{"hours": 1.0, "rate_cents": 20000}],
        )
        assert first["status"] == "FILED"

        # Intersecting [2026-08-15, 2026-09-15) is rejected.
        resp = api.create_fee_application(
            {
                "engagement_id": eng["id"],
                "period_start": "2026-08-15T00:00:00Z",
                "period_end": "2026-09-15T00:00:00Z",
                "time_entries": [{"hours": 1.0, "rate_cents": 20000}],
                "expenses_cents": 0,
            },
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_FEE_PERIOD_OVERLAP)

        # Half-open adjacency at 2026-08-31 is NOT an overlap.
        adj = api.create_fee_application(
            {
                "engagement_id": eng["id"],
                "period_start": "2026-08-31T00:00:00Z",
                "period_end": "2026-09-30T00:00:00Z",
                "time_entries": [{"hours": 1.0, "rate_cents": 20000}],
                "expenses_cents": 0,
            },
            RECEIVER,
        )
        assert validate_success(adj, 201)["status"] == "FILED"

    def test_fee_application_period_adjacency_accepted(self, api):
        """PRD §3.5: "the periods of non-`DENIED` applications on the same
        engagement must not overlap, failing with `ERR_FEE_PERIOD_OVERLAP`,
        though gaps and abutting periods are permitted."

        Design: Difficulty/resource_temporal_overlap/fee_application_period_overlap_half_open
        """
        case = create_case()
        eng = create_approved_engagement(case["id"], fee_cap_cents=5000000)
        create_fee_application(
            eng["id"], period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
        )
        # A gap period [2026-10-01, 2026-10-31) is permitted.
        gap = api.create_fee_application(
            {
                "engagement_id": eng["id"],
                "period_start": "2026-10-01T00:00:00Z",
                "period_end": "2026-10-31T00:00:00Z",
                "time_entries": [{"hours": 1.0, "rate_cents": 20000}],
                "expenses_cents": 0,
            },
            RECEIVER,
        )
        assert validate_success(gap, 201)["status"] == "FILED"


class TestFeeRequestCalculation:
    def test_fee_lodestar_vs_contingent_percentage(self, api):
        """PRD §2.6: "Fee requests on an hourly engagement round each
        individual time-entry line to whole cents using round-half-up before
        the lines are summed; the rounding of each entry precedes summation,
        and only then are expenses added"
        PRD §2.6: "Fee requests on a contingent engagement round the
        percentage-of-recovery product to whole cents, round-half-up, before
        expenses are added."

        Design: Difficulty/dual_variant_calc/fee_lodestar_vs_contingent_percentage
        """
        case = create_case()
        hourly = create_approved_engagement(
            case["id"], professional_name="L. Lawyer", firm_name="Law LLP",
            role_type="COUNSEL", fee_arrangement="HOURLY",
            hourly_rate_cents=20000, fee_cap_cents=5000000,
        )
        contingent = validate_success(
            api.create_engagement(
                {
                    "case_id": case["id"],
                    "professional_name": "A. Accountant",
                    "firm_name": "Acct LLC",
                    "role_type": "ACCOUNTANT",
                    "fee_arrangement": "CONTINGENT",
                    "contingency_pct": 0.10,
                    "fee_cap_cents": 5000000,
                },
                RECEIVER,
            ),
            201,
        )
        decide_engagement(contingent["id"], "APPROVE")
        hourly_app = create_fee_application(
            hourly["id"],
            period_start="2026-08-01T00:00:00Z", period_end="2026-08-31T00:00:00Z",
            time_entries=[{"hours": 10.0, "rate_cents": 20000}], expenses_cents=0,
        )
        contingent_app = validate_success(
            api.create_fee_application(
                {
                    "engagement_id": contingent["id"],
                    "period_start": "2026-08-01T00:00:00Z",
                    "period_end": "2026-08-31T00:00:00Z",
                    "recovery_basis_cents": 3000000,
                    "expenses_cents": 0,
                },
                RECEIVER,
            ),
            201,
        )
        assert hourly_app["requested_amount_cents"] == 200000
        assert contingent_app["requested_amount_cents"] == 300000
        assert hourly_app["requested_amount_cents"] != contingent_app["requested_amount_cents"]

    def test_fee_lodestar_and_contingent_diverge_for_same_work(self, api):
        """PRD §2.6: "Fee requests on an hourly engagement round each
        individual time-entry line to whole cents using round-half-up before
        the lines are summed; the rounding of each entry precedes summation,
        and only then are expenses added"
        PRD §2.6: "Fee requests on a contingent engagement round the
        percentage-of-recovery product to whole cents, round-half-up, before
        expenses are added."

        Design: Difficulty/dual_variant_calc/fee_lodestar_vs_contingent_percentage
        """
        case = create_case()
        hourly = create_approved_engagement(
            case["id"], role_type="COUNSEL", fee_arrangement="HOURLY",
            hourly_rate_cents=20000, fee_cap_cents=5000000,
        )
        contingent = validate_success(
            api.create_engagement(
                {
                    "case_id": case["id"],
                    "professional_name": "A. Accountant",
                    "firm_name": "Acct LLC",
                    "role_type": "ACCOUNTANT",
                    "fee_arrangement": "CONTINGENT",
                    "contingency_pct": 0.10,
                    "fee_cap_cents": 5000000,
                },
                RECEIVER,
            ),
            201,
        )
        decide_engagement(contingent["id"], "APPROVE")
        hourly_app = create_fee_application(
            hourly["id"],
            time_entries=[{"hours": 10.0, "rate_cents": 20000}], expenses_cents=0,
        )
        contingent_app = validate_success(
            api.create_fee_application(
                {
                    "engagement_id": contingent["id"],
                    "period_start": "2026-08-01T00:00:00Z",
                    "period_end": "2026-08-31T00:00:00Z",
                    "recovery_basis_cents": 3000000,
                    "expenses_cents": 0,
                },
                RECEIVER,
            ),
            201,
        )
        # 10.0 x 20000 = 200000 lodestar; 0.10 x 3000000 = 300000 contingent.
        assert hourly_app["requested_amount_cents"] == 200000
        assert contingent_app["requested_amount_cents"] == 300000

    def test_fee_per_entry_rounding_before_sum(self, api):
        """PRD §2.6: "Fee requests on an hourly engagement round each
        individual time-entry line to whole cents using round-half-up before
        the lines are summed; the rounding of each entry precedes summation,
        and only then are expenses added (summing first and rounding once
        can differ by a cent, and that order is not the contract)."

        Design: Difficulty/combinatorial_formula/fee_per_entry_rounding_before_sum
        """
        case = create_case()
        eng = create_approved_engagement(
            case["id"], professional_name="L. Lawyer", firm_name="Law LLP",
            role_type="COUNSEL", fee_arrangement="HOURLY",
            hourly_rate_cents=20000, fee_cap_cents=5000000,
        )
        app = create_fee_application(
            eng["id"],
            period_start="2026-08-01T00:00:00Z", period_end="2026-08-31T00:00:00Z",
            time_entries=[
                {"hours": 2.5, "rate_cents": 33333},
                {"hours": 2.5, "rate_cents": 13333},
            ],
            expenses_cents=5000,
        )
        # Per-entry round-half-up: 83333 + 33333 + 5000 == 121666.
        assert app["requested_amount_cents"] == 121666
        assert app["requested_amount_cents"] != 121665

    def test_fee_per_entry_rounding_differs_from_sum_then_round(self, api):
        """PRD §2.6: "the rounding of each entry precedes summation, and
        only then are expenses added (summing first and rounding once can
        differ by a cent, and that order is not the contract)."

        Design: Difficulty/combinatorial_formula/fee_per_entry_rounding_before_sum
        """
        case = create_case()
        eng = create_approved_engagement(case["id"], fee_cap_cents=5000000)
        app = create_fee_application(
            eng["id"],
            time_entries=[
                {"hours": 2.5, "rate_cents": 33333},
                {"hours": 2.5, "rate_cents": 13333},
            ],
            expenses_cents=5000,
        )
        # 2.5*33333 = 83332.5 -> 83333; 2.5*13333 = 33332.5 -> 33333.
        assert app["requested_amount_cents"] == 83333 + 33333 + 5000


class TestFeeApprovalGuards:
    def test_court_approval_above_requested_rejected(self, api):
        """PRD §3.5: "An approval must supply `approved_amount_cents` (else
        `ERR_INVALID_REQUEST`) not exceeding the computed
        `requested_amount_cents` (else `ERR_AMOUNT_EXCEEDS_REQUEST`,
        HTTP 422)."

        Design: Corner/validations/court_approval_above_requested_rejected
        """
        case = create_case()
        eng = create_approved_engagement(case["id"], hourly_rate_cents=25000)
        app = create_fee_application(
            eng["id"], time_entries=[{"hours": 1.0, "rate_cents": 25000}],
        )
        assert app["requested_amount_cents"] == 25000

        resp = api.decide_fee_application(
            app["id"], {"decision": "APPROVE", "approved_amount_cents": 25001}, COURT,
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_REQUEST)

    def test_fee_cap_boundary_at_approval(self, api):
        """PRD §3.5: "the sum of `approved_amount_cents` over the
        engagement's applications already in `APPROVED` or `PAID` status,
        plus the newly approved amount, must not exceed `fee_cap_cents` —
        reaching the cap exactly is permitted — and a breach is rejected
        with `ERR_FEE_CAP_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/fee_cap_boundary_at_approval
        """
        case = create_case()
        eng = create_approved_engagement(case["id"], fee_cap_cents=100000)
        f1 = create_fee_application(
            eng["id"], period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            time_entries=[{"hours": 3.0, "rate_cents": 20000}],
        )
        decide_fee_application(f1["id"], "APPROVE", 60000)

        f2 = create_fee_application(
            eng["id"], period_start="2026-09-01T00:00:00Z",
            period_end="2026-09-30T00:00:00Z",
            time_entries=[{"hours": 2.0, "rate_cents": 20000}],
        )
        f3 = create_fee_application(
            eng["id"], period_start="2026-10-01T00:00:00Z",
            period_end="2026-10-31T00:00:00Z",
            time_entries=[{"hours": 1.0, "rate_cents": 20000}],
        )

        ok = api.decide_fee_application(
            f2["id"], {"decision": "APPROVE", "approved_amount_cents": 40000}, COURT,
        )
        assert validate_success(ok, 200)["status"] == "APPROVED", (
            "committed 60000 + 40000 == cap exactly is permitted"
        )

        over = api.decide_fee_application(
            f3["id"], {"decision": "APPROVE", "approved_amount_cents": 20000}, COURT,
        )
        validate_error(over, ApiErrorId.ERR_FEE_CAP_EXCEEDED)


class TestFeePayAndExhaustion:
    def test_engagement_exhausted_auto_transition_at_cap(self, api):
        """PRD §3.5: "When that running total reaches or exceeds
        `fee_cap_cents`, the engagement automatically moves from `APPROVED`
        to `EXHAUSTED`, and an exhausted engagement rejects any further fee
        applications with `ERR_ENGAGEMENT_NOT_APPROVED`."

        Design: Corner/state_machines/engagement_exhausted_auto_transition_at_cap
        """
        case, _asset = setup_case_with_cash(100000)
        eng = create_approved_engagement(case["id"], fee_cap_cents=100000)
        app = create_fee_application(
            eng["id"], time_entries=[{"hours": 1.0, "rate_cents": 100000}],
        )
        decide_fee_application(app["id"], "APPROVE", 100000)
        v = get_case(case["id"])["version"]
        paid = pay_fee_application(app["id"], v)
        assert paid["status"] == "PAID"

        eng_data = validate_success(api.get_engagement(eng["id"], RECEIVER), 200)
        assert eng_data["total_fees_paid_cents"] == 100000
        assert eng_data["status"] == "EXHAUSTED", (
            "hitting the cap exactly (>=) triggers the auto-transition"
        )

        resp = api.create_fee_application(
            {
                "engagement_id": eng["id"],
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-09-30T00:00:00Z",
                "time_entries": [{"hours": 1.0, "rate_cents": 20000}],
                "expenses_cents": 0,
            },
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_APPROVED)

    def test_fee_pay_state_beats_fiscal(self, api):
        """PRD §2.10: "From-state validity of the requested transition —
        liquidation requires an `IDENTIFIED` asset, a decision requires the
        instrument's pending state, a fee payment requires an `APPROVED`
        application, a distribution payment requires a `SCHEDULED` payment,
        discharge requires a `DISTRIBUTING` case — else `ERR_INVALID_STATE`
        (HTTP 409)."
        PRD §2.10: "12. Fiscal checks, always last: cash sufficiency for
        fee payment, distribution payment, and expenditure approval
        (`ERR_INSUFFICIENT_ESTATE_FUNDS`)"

        Design: Difficulty/priority_pair_validation_conflict/fee_pay_state_beats_fiscal
        """
        case, _asset = setup_case_with_cash(100000)
        eng = create_approved_engagement(case["id"], fee_cap_cents=1000000)
        app = create_fee_application(
            eng["id"], time_entries=[{"hours": 1.0, "rate_cents": 100000}],
        )
        decide_fee_application(app["id"], "APPROVE", 100000)
        v1 = get_case(case["id"])["version"]
        paid = pay_fee_application(app["id"], v1)
        assert paid["status"] == "PAID"
        after = get_case(case["id"])
        assert after["cash_on_hand_cents"] == 0

        # Second pay carries a fresh OCC version, so it reaches the failing
        # state check; the priority-6 state error beats the priority-12 fiscal.
        resp = api.pay_fee_application(
            app["id"], {"expected_case_version": after["version"]}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fee_pay_second_pay_with_fresh_version_hits_state_gate(self, api):
        """PRD §2.10: "From-state validity of the requested transition —
        liquidation requires an `IDENTIFIED` asset, a decision requires the
        instrument's pending state, a fee payment requires an `APPROVED`
        application, a distribution payment requires a `SCHEDULED` payment,
        discharge requires a `DISTRIBUTING` case — else `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/fee_pay_state_beats_fiscal
        """
        case, _asset = setup_case_with_cash(100000)
        eng = create_approved_engagement(case["id"], fee_cap_cents=1000000)
        app = create_fee_application(
            eng["id"], time_entries=[{"hours": 1.0, "rate_cents": 100000}],
        )
        decide_fee_application(app["id"], "APPROVE", 100000)
        v1 = get_case(case["id"])["version"]
        pay_fee_application(app["id"], v1)
        after = get_case(case["id"])
        assert after["cash_on_hand_cents"] == 0

        # Even with the up-to-date version, the application is PAID, so the
        # state gate fires before the fiscal check (cash 0 < approved 100000).
        resp = api.pay_fee_application(
            app["id"], {"expected_case_version": after["version"]}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fee_pay_stale_case_version_rejected(self, api):
        """PRD §2.7: "Each of these requests must carry
        `expected_case_version`, a non-optional input holding the `version`
        of the case as the client last read it. If the case's current
        `version` has advanced past that value — because a liquidation, a
        fee payment, an expenditure approval, a distribution payment, or a
        void has since landed — the request is rejected with
        `ERR_STALE_CASE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_fee_pay_stale_case_version_rejected
        """
        case, _asset = setup_case_with_cash(300000)
        eng = create_approved_engagement(case["id"], fee_cap_cents=1000000)
        f1 = create_fee_application(
            eng["id"], period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-31T00:00:00Z",
            time_entries=[{"hours": 5.0, "rate_cents": 20000}],
        )
        decide_fee_application(f1["id"], "APPROVE", 100000)
        f2 = create_fee_application(
            eng["id"], period_start="2026-09-01T00:00:00Z",
            period_end="2026-09-30T00:00:00Z",
            time_entries=[{"hours": 2.5, "rate_cents": 20000}],
        )
        decide_fee_application(f2["id"], "APPROVE", 50000)

        v_obs = get_case(case["id"])["version"]
        paid = pay_fee_application(f1["id"], v_obs)
        assert paid["status"] == "PAID"

        v_after = get_case(case["id"])["version"]
        assert v_after == v_obs + 1, "the pay incremented Case.version by exactly 1"

        resp = api.pay_fee_application(
            f2["id"], {"expected_case_version": v_obs}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

    def test_fee_pay_version_increments_exactly_one(self, api):
        """PRD §3.5: "Paying moves the application to `PAID`, debits the
        approved amount from `cash_on_hand_cents`, increments the case's
        `version`, recomputes `posture`, and recomputes the engagement's
        `total_fees_paid_cents`"

        Design: Corner/cross_cutting_layers/occ_fee_pay_stale_case_version_rejected
        """
        case, _asset = setup_case_with_cash(300000)
        eng = create_approved_engagement(case["id"], fee_cap_cents=1000000)
        app = create_fee_application(
            eng["id"], time_entries=[{"hours": 1.0, "rate_cents": 20000}],
        )
        decide_fee_application(app["id"], "APPROVE", 20000)

        before = get_case(case["id"])
        pay_fee_application(app["id"], before["version"])
        after = get_case(case["id"])
        assert after["version"] == before["version"] + 1
        assert after["cash_on_hand_cents"] == 300000 - 20000
