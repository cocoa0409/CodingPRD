"""Portfolio segmentation, loan intake, charge-offs, and recoveries (PRD §3.2–§3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_loan,
    assert_portfolio_segment,
    charge_off_payload,
    create_loan_payload,
    create_segment,
    create_segment_payload,
    get_segment,
    record_charge_off,
    recovery_payload,
    setup_run_environment,
    setup_watch_segment,
    validate_error,
    validate_success,
)


class TestSegmentCreation:
    def test_segment_create_ignores_client_system_fields(self, api, credit_analyst_headers):
        """PRD §2.9: "Request body shape: required fields are present, types are valid, enum members belong to their declared sets, and period strings match the quarterly format, else `ERR_INVALID_REQUEST`. Unknown fields and system-managed fields supplied in a request body are ignored rather than rejected."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/segment_create_system_fields_input_ignored
        """
        supplied_id = "11111111-1111-4111-8111-111111111111"
        res = api.create_portfolio_segment(
            {
                "segment_code": "CC-PRIME-2024",
                "name": "Prime Cards",
                "product_type": "CREDIT_CARD",
                "risk_rating_band": "PRIME",
                "vintage_year": 2024,
                "id": supplied_id,
                "created_at": "2020-01-01T00:00:00.000Z",
                "version": 99,
            },
            credit_analyst_headers,
        )
        data = validate_success(res, 201)
        assert_portfolio_segment(data)
        assert data["id"] != supplied_id, "server must ignore the client-supplied id"
        assert data["version"] != 99, "server must ignore the client-supplied version"
        assert data["status"] == "OPEN"
        assert data["origination_total_cents"] == 0

    def test_duplicate_segment_code_rejected(self, api, credit_analyst_headers):
        """PRD §3.2: "A `CreditAnalyst` creates a portfolio segment with a `segment_code` — a business identifier that must be globally unique, with duplicates rejected as `ERR_DUPLICATE_SEGMENT_CODE` (HTTP 409) — a display `name`, a `product_type` of `CREDIT_CARD`, `AUTO`, `MORTGAGE`, `SMALL_BUSINESS`, or `PERSONAL`, a `risk_rating_band` of `PRIME`, `NEAR_PRIME`, `SUBPRIME`, or `DEEP_SUBPRIME`, and the `vintage_year` of origination."

        Design: Corner/validations/duplicate_segment_code_rejected
        """
        create_segment(segment_code="CC-PRIME-2024")
        res = api.create_portfolio_segment(
            create_segment_payload(
                segment_code="CC-PRIME-2024",
                name="Duplicate",
                product_type="AUTO",
                risk_rating_band="SUBPRIME",
                vintage_year=2025,
            ),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SEGMENT_CODE)


    def test_duplicate_loan_number_rejected(self, api, credit_analyst_headers):
        """PRD §3.3: "A `CreditAnalyst` books a loan into a segment by supplying the target `segment_id`, a globally unique `loan_number` (duplicates are rejected with `ERR_DUPLICATE_LOAN_NUMBER`, HTTP 409), the current `amortized_cost_cents` — which must be greater than zero — and the loan's `risk_rating` of `PASS`, `SPECIAL_MENTION`, `SUBSTANDARD`, `DOUBTFUL`, or `LOSS`."

        Design: Corner/validations/duplicate_loan_number_rejected
        """
        segment_1 = create_segment(segment_code="S1", name="Seg 1")
        segment_2 = create_segment(segment_code="S2", name="Seg 2", product_type="AUTO",
                                   risk_rating_band="NEAR_PRIME")
        validate_success(api.create_loan(
            create_loan_payload(segment_1["id"], loan_number="LN-DUP",
                                amortized_cost_cents=1_000, risk_rating="PASS"),
            credit_analyst_headers), 201)
        # Uniqueness is global: a different segment does not permit reuse.
        res = api.create_loan(
            create_loan_payload(segment_2["id"], loan_number="LN-DUP",
                                amortized_cost_cents=2_000, risk_rating="PASS"),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_LOAN_NUMBER, 409)


class TestLoanIntake:
    def test_loan_defaults_applied(self, api, credit_analyst_headers):
        """PRD §3.3: "Two optional inputs complete the picture: `delinquency_days`, the days past due, which defaults to zero and may never be negative, and `collateral_value_cents`, the appraised collateral value, which likewise defaults to zero and may never be negative."

        Design: Corner/entities/loan_defaults_applied
        """
        segment = create_segment(name="Auto NP", product_type="AUTO",
                                 risk_rating_band="NEAR_PRIME")
        res = api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-D1",
                                amortized_cost_cents=25_000, risk_rating="PASS"),
            credit_analyst_headers,
        )
        data = validate_success(res, 201)
        assert_loan(data)
        assert data["delinquency_days"] == 0
        assert data["collateral_value_cents"] == 0
        assert data["status"] == "ACTIVE"
        assert data["individually_evaluated"] is False

    def test_loan_invalid_risk_rating_rejected(self, api, credit_analyst_headers):
        """PRD §2.9: "Request body shape: required fields are present, types are valid, enum members belong to their declared sets, and period strings match the quarterly format, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/loan_invalid_enum_rejected
        """
        segment = create_segment(name="Auto NP", product_type="AUTO",
                                 risk_rating_band="NEAR_PRIME")
        res = api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-E1",
                                amortized_cost_cents=25_000, risk_rating="VERY_BAD"),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_loan_get_not_found(self, api, credit_analyst_headers):
        """PRD §2.9: "Path existence: every identifier in the request path is resolved against existing resources in left-to-right order, and the first identifier that does not resolve rejects the whole request with `ERR_NOT_FOUND` (HTTP 404) before any later identifier — or any body rule — is examined."

        Design: Corner/entities/loan_get_not_found_returns_404
        """
        res = api.get_loan(NON_EXISTENT_UUID, credit_analyst_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_individually_evaluated_threshold_boundary(self, api, credit_analyst_headers):
        """PRD §3.3: "A loan is individually evaluated when its `risk_rating` is `SUBSTANDARD`, `DOUBTFUL`, or `LOSS`, or when its `amortized_cost_cents` is at least one hundred million cents — one million dollars. The boundary is inclusive: a loan whose amortized cost equals the threshold exactly is individually evaluated."

        Design: Corner/entities/individually_evaluated_boundary
        """
        segment = create_segment(name="Prime Mtg", product_type="MORTGAGE",
                                 risk_rating_band="PRIME")
        below = validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-T1",
                                amortized_cost_cents=99_999_999, risk_rating="PASS"),
            credit_analyst_headers), 201)
        at = validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-T2",
                                amortized_cost_cents=100_000_000, risk_rating="PASS"),
            credit_analyst_headers), 201)
        rated = validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-T3",
                                amortized_cost_cents=50_000, risk_rating="SUBSTANDARD"),
            credit_analyst_headers), 201)
        assert below["individually_evaluated"] is False
        assert at["individually_evaluated"] is True
        assert rated["individually_evaluated"] is True

    def test_loan_computed_flag_input_ignored(self, api, credit_analyst_headers):
        """PRD §2.9: "Request body shape: required fields are present, types are valid, enum members belong to their declared sets, and period strings match the quarterly format, else `ERR_INVALID_REQUEST`. Unknown fields and system-managed fields supplied in a request body are ignored rather than rejected."
        PRD §3.3: "The boundary is inclusive: a loan whose amortized cost equals the threshold exactly is individually evaluated."

        Design: Corner/entities/loan_computed_flag_input_ignored
        """
        segment = create_segment(name="Prime Mtg", product_type="MORTGAGE",
                                 risk_rating_band="PRIME")
        res = api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-C1",
                                amortized_cost_cents=100_000_000, risk_rating="PASS",
                                individually_evaluated=False),
            credit_analyst_headers,
        )
        data = validate_success(res, 201)
        assert data["individually_evaluated"] is True, (
            "computed value must prevail over the client-supplied flag"
        )

    def test_loans_create_missing_auth_header(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/loans_create_missing_auth_header
        """
        res = api.create_loan(
            {
                "segment_id": "33333333-3333-4333-8333-333333333333",
                "loan_number": "LN-H1",
                "amortized_cost_cents": 1000,
                "risk_rating": "PASS",
            },
            headers=None,
        )
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_auditor_write_forbidden(self, api, external_auditor_headers):
        """PRD §2.1: "An `ExternalAuditor` is read-only across the system except for disclosure sign-off and return-for-revision."
        PRD §2.1: "A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/auditor_write_forbidden
        """
        segment = create_segment()
        res = api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-AU",
                                amortized_cost_cents=1000, risk_rating="PASS"),
            external_auditor_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)


class TestChargeOffsAndRecoveries:
    def test_charge_off_exceeds_balance_rejected(self, api, credit_analyst_headers):
        """PRD §3.3: "The amount must be at least one cent and no more than the loan's current `amortized_cost_cents`; anything outside that range is rejected with `ERR_CHARGE_OFF_EXCEEDS_BALANCE` (HTTP 422)."
        PRD §3.3: "When the amount equals the balance exactly, the charge-off is full: the amortized cost falls to zero and the loan transitions `ACTIVE` → `CHARGED_OFF`, which is terminal."

        Design: Corner/validations/charge_off_exceeds_balance_rejected
        """
        segment = create_segment(name="Auto NP", product_type="AUTO",
                                 risk_rating_band="NEAR_PRIME", vintage_year=2023)
        loan = validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-CB",
                                amortized_cost_cents=100_000, risk_rating="PASS"),
            credit_analyst_headers), 201)

        over = api.charge_off_loan(loan["id"], charge_off_payload(100_001),
                                   credit_analyst_headers)
        validate_error(over, ApiErrorId.ERR_CHARGE_OFF_EXCEEDS_BALANCE, 422)

        exact = api.charge_off_loan(loan["id"], charge_off_payload(100_000),
                                    credit_analyst_headers)
        data = validate_success(exact, 200)
        assert data["status"] == "CHARGED_OFF"
        assert data["amortized_cost_cents"] == 0

    def test_recovery_exceeds_charge_off_rejected(self, api, credit_analyst_headers):
        """PRD §3.3: "On a `CHARGED_OFF` loan, the cap is cumulative: the loan's `recovered_total_cents` plus the new amount may not exceed its `charged_off_total_cents`, else the request is rejected with `ERR_RECOVERY_EXCEEDS_CHARGE_OFF` (HTTP 422)."

        Design: Corner/validations/recovery_exceeds_charge_off_rejected
        """
        segment = create_segment(name="Auto NP", product_type="AUTO",
                                 risk_rating_band="NEAR_PRIME", vintage_year=2023)
        loan = validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-RC",
                                amortized_cost_cents=100_000, risk_rating="PASS"),
            credit_analyst_headers), 201)
        record_charge_off(loan["id"], 50_000)

        over = api.record_recovery(loan["id"], recovery_payload(50_001),
                                   credit_analyst_headers)
        validate_error(over, ApiErrorId.ERR_RECOVERY_EXCEEDS_CHARGE_OFF, 422)

        exact = api.record_recovery(loan["id"], recovery_payload(50_000),
                                    credit_analyst_headers)
        data = validate_success(exact, 200)
        assert data["recovered_total_cents"] == 50_000

    def test_recovery_on_never_charged_loan_rejected(self, api, credit_analyst_headers):
        """PRD §3.3: "A recovery may also be recorded against an `ACTIVE` loan that was partially charged off; there is simply nothing to recover when the loan's `charged_off_total_cents` is zero, and such a request is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409), while the same cumulative cap applies otherwise."

        Design: Corner/state_machines/recovery_on_never_charged_loan_rejected
        """
        segment = create_segment(name="Auto NP", product_type="AUTO",
                                 risk_rating_band="NEAR_PRIME", vintage_year=2023)
        loan = validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-R9",
                                amortized_cost_cents=100_000, risk_rating="PASS"),
            credit_analyst_headers), 201)
        res = api.record_recovery(loan["id"], recovery_payload(1_000),
                                  credit_analyst_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_partial_charge_off_keeps_active_and_boundary_rate(self, api, credit_analyst_headers):
        """PRD §3.3: "When the amount is less than the balance, the charge-off is partial: the loan stays `ACTIVE`, its `amortized_cost_cents` is reduced by the amount, and its `charged_off_total_cents` grows by the amount."
        PRD §3.3: "The comparison is strict: a rate of exactly two hundred basis points leaves an `OPEN` segment open."

        Design: Corner/state_machines/partial_charge_off_keeps_active_and_boundary_rate
        """
        segment = create_segment(name="Auto NP", product_type="AUTO",
                                 risk_rating_band="NEAR_PRIME", vintage_year=2023)
        loan_1 = validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-P1",
                                amortized_cost_cents=100_000, risk_rating="PASS"),
            credit_analyst_headers), 201)
        validate_success(api.create_loan(
            create_loan_payload(segment["id"], loan_number="LN-P2",
                                amortized_cost_cents=100_000, risk_rating="PASS"),
            credit_analyst_headers), 201)

        data = validate_success(api.charge_off_loan(
            loan_1["id"], charge_off_payload(4_000), credit_analyst_headers), 200)
        assert data["status"] == "ACTIVE"
        assert data["amortized_cost_cents"] == 96_000
        assert data["charged_off_total_cents"] == 4_000

        seg = get_segment(segment["id"])
        # round_half_up(4000 * 10000 / 200000) == 200; strictly-greater rule keeps OPEN
        assert seg["charge_off_rate_bps"] == 200
        assert seg["status"] == "OPEN"


class TestSegmentWatchGating:
    def test_loan_create_in_watch_segment_rejected(self, api, credit_analyst_headers):
        """PRD §3.3: "Booking is only possible into an `OPEN` segment; a segment sitting in `WATCH` refuses new loans with `ERR_SEGMENT_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/loan_create_requires_segment_open
        """
        env = setup_watch_segment()
        assert env.segment["status"] == "WATCH"

        res = api.create_loan(
            create_loan_payload(env.segment["id"], loan_number="LN-W3",
                                amortized_cost_cents=5_000, risk_rating="PASS"),
            credit_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_NOT_OPEN, 409)

    def test_segment_watch_clears_after_recovery_allowing_loan_create(self, api, credit_analyst_headers):
        """PRD §3.3: "Recording the recovery grows the loan's `recovered_total_cents` by the amount, grows the segment's `ytd_recoveries_cents` by the amount, and recomputes the segment's charge-off rate exactly as above — this time in the healing direction: when the recomputed rate is two hundred basis points or less and the segment sits in `WATCH`, it returns `WATCH` → `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/loan_create_requires_segment_open
        """
        env = setup_watch_segment()
        assert env.segment["status"] == "WATCH"

        data = validate_success(api.record_recovery(
            env.charged_loan["id"], recovery_payload(100_000), credit_analyst_headers), 200)
        assert data["recovered_total_cents"] == 100_000

        seg = get_segment(env.segment["id"])
        assert seg["ytd_recoveries_cents"] == 100_000
        assert seg["charge_off_rate_bps"] == 0
        assert seg["status"] == "OPEN"

        res = api.create_loan(
            create_loan_payload(env.segment["id"], loan_number="LN-W3",
                                amortized_cost_cents=5_000, risk_rating="PASS"),
            credit_analyst_headers,
        )
        assert validate_success(res, 201)["status"] == "ACTIVE"


class TestChargeOffCascade:
    def test_charge_off_cascades_segment_counters_and_watch(self, api, credit_analyst_headers):
        """PRD §3.3: "As the first hop, the segment's `ytd_gross_charge_offs_cents` grows by the charged-off amount. As the second hop, the segment's `charge_off_rate_bps` is recomputed as net charge-offs — `ytd_gross_charge_offs_cents` minus `ytd_recoveries_cents` — multiplied by ten thousand and divided by `origination_total_cents`, rounded half-up to a whole basis point, or zero outright when the segment's origination total is zero; if that recomputed rate is strictly greater than two hundred basis points and the segment is `OPEN`, the segment moves `OPEN` → `WATCH`."

        Design: Difficulty/transitive_cascade/charge_off_watch_run_flag_chain
        """
        env = setup_run_environment(loan_specs=[
            {"amortized_cost_cents": 100_000, "risk_rating": "PASS"},
            {"amortized_cost_cents": 100_000, "risk_rating": "PASS"},
        ])
        loan_1, loan_2 = env.loans

        data = validate_success(api.charge_off_loan(
            loan_1["id"], charge_off_payload(100_000), credit_analyst_headers), 200)
        assert data["status"] == "CHARGED_OFF"
        assert data["amortized_cost_cents"] == 0

        seg = get_segment(env.segments[0]["id"])
        assert seg["ytd_gross_charge_offs_cents"] == 100_000  # hop 1
        assert seg["charge_off_rate_bps"] == 5_000            # hop 2: 100000*10000/200000
        assert seg["status"] == "WATCH"                       # 5000 > 200

    def test_segment_watch_flags_draft_runs_for_review(self, api, credit_analyst_headers):
        """PRD §3.3: "As the third hop, the moment a segment enters `WATCH`, every model run currently in `DRAFT` has its `needs_segmentation_review` flag set true — an informational warning that the segmentation those runs were drafted against has deteriorated."

        Design: Difficulty/transitive_cascade/charge_off_watch_run_flag_chain
        """
        env = setup_run_environment(loan_specs=[
            {"amortized_cost_cents": 100_000, "risk_rating": "PASS"},
            {"amortized_cost_cents": 100_000, "risk_rating": "PASS"},
        ])
        run = env.run
        assert run["status"] == "DRAFT"
        assert run["needs_segmentation_review"] is False

        record_charge_off(env.loans[0]["id"], 100_000)

        updated = validate_success(api.get_model_run(run["id"], credit_analyst_headers), 200)
        assert updated["needs_segmentation_review"] is True  # hop 3
        assert updated["status"] == "DRAFT"
