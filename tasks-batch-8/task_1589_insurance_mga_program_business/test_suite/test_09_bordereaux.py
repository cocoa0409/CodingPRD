"""Bordereaux: per-row rounding order, submit-time data-quality gate
(empty rows, period covered, duplicate rows, unknown policy, row mismatch,
total mismatch), acceptance side effects, and the reject/revise loop."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    bind_policy,
    get_policy_fresh,
    make_carrier_underwriter_headers,
    quote_policy,
    setup_active_program,
    validate_error,
    validate_success,
)

UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]

DUE = "2026-09-15T00:00:00Z"


def _bound_policy(api, program, name, **overrides):
    policy = quote_policy(program, insured_name=name, **overrides)
    return bind_policy(policy)


def _draft_premium_bordereau(api, program, rows, totals, period="2026-08"):
    return validate_success(api.create_bordereau(program["id"], {
        "bordereau_type": "PREMIUM", "period_label": period, "due_date": DUE,
        "rows": rows, "declared_totals": totals}, FIN), expected_status=201)


class TestBordereauRoundingOrder:
    def test_per_row_round_then_sum_submit_succeeds(self, api):
        """PRD §3.7: "each row's commission is recomputed as that row's
        written premium multiplied by the program's `commission_rate_pct`,
        rounded half-up to whole cents, and the commission total is the sum of
        those per-row rounded figures — the per-row rounding happens before
        summation, pinned, because summing unrounded amounts and rounding once
        yields different cents and is wrong."

        Design: Difficulty/combinatorial_formula/bordereau_per_row_round_then_sum
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 1000000},
            allocation_overrides={"allocated_cents": 600000},
            filing_overrides={"policy_fee_cents": 5004})
        # Each policy gross: 100*1500 + 5004 = 155004; per-row commission
        # round_half_up(155004*0.15) = 23251.
        policies = [_bound_policy(api, program, f"R{i}") for i in (1, 2, 3)]
        rows = [{"policy_id": p["id"], "written_premium_cents": 155004,
                 "commission_cents": 23251} for p in policies]
        bor = _draft_premium_bordereau(
            api, program, rows,
            {"premium_cents": 465012, "commission_cents": 69753})
        assert bor["computed_totals"]["commission_cents"] == 69753
        assert bor["computed_totals"]["premium_cents"] == 465012
        assert bor["row_count"] == 3

        submitted = validate_success(api.submit_bordereau(bor["id"], FIN))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["computed_totals"]["commission_cents"] == 69753

    def test_computed_totals_filled_on_draft_create(self, api):
        """PRD §3.7: "The server maintains `computed_totals` and `row_count`
        on the draft: for `PREMIUM` bordereaux, each row's commission is
        recomputed as that row's written premium multiplied by the program's
        `commission_rate_pct`, rounded half-up to whole cents, and the
        commission total is the sum of those per-row rounded figures."

        Design: Difficulty/combinatorial_formula/bordereau_per_row_round_then_sum
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 1000000},
            allocation_overrides={"allocated_cents": 600000},
            filing_overrides={"policy_fee_cents": 5004})
        policies = [_bound_policy(api, program, f"D{i}") for i in (1, 2, 3)]
        rows = [{"policy_id": p["id"], "written_premium_cents": 155004,
                 "commission_cents": 23251} for p in policies]
        bor = _draft_premium_bordereau(
            api, program, rows,
            {"premium_cents": 465012, "commission_cents": 69753})
        # Per-row rounding pinned BEFORE summation: 3 x 23251 = 69753, not the
        # sum-then-round 69752.
        assert bor["computed_totals"] == {
            "premium_cents": 465012, "commission_cents": 69753}
        assert bor["row_count"] == 3

    def test_sum_then_round_declared_total_rejected(self, api):
        """PRD §3.7: "`declared_totals` must equal `computed_totals` exactly
        (`ERR_BORDEREAU_TOTAL_MISMATCH`)" — the sum-then-round figure 69752
        (465012*0.15 = 69751.8) differs from the pinned per-row total 69753.

        Design: Corner/calculations/bordereau_declared_totals_mismatch_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 1000000},
            allocation_overrides={"allocated_cents": 600000},
            filing_overrides={"policy_fee_cents": 5004})
        policies = [_bound_policy(api, program, f"M{i}") for i in (1, 2, 3)]
        rows = [{"policy_id": p["id"], "written_premium_cents": 155004,
                 "commission_cents": 23251} for p in policies]
        bor = _draft_premium_bordereau(
            api, program, rows,
            {"premium_cents": 465012, "commission_cents": 69752})
        resp = api.submit_bordereau(bor["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_BORDEREAU_TOTAL_MISMATCH)
        fresh = validate_success(api.get_bordereau(bor["id"], FIN))
        assert fresh["status"] == "DRAFT"


class TestBordereauSubmitGate:
    def test_empty_bordereau_submit_rejected(self, api):
        """PRD §3.7: "the bordereau must contain at least one row
        (`ERR_EMPTY_BORDEREAU`)" — and "A draft may legitimately hold zero
        rows while it is being assembled."

        Design: Difficulty/boundary_precision_check/empty_bordereau_zero_rows_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        bor = _draft_premium_bordereau(
            api, program, [], {"premium_cents": 0, "commission_cents": 0})
        assert bor["row_count"] == 0, "empty draft is legal"
        resp = api.submit_bordereau(bor["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_EMPTY_BORDEREAU)
        fresh = validate_success(api.get_bordereau(bor["id"], FIN))
        assert fresh["status"] == "DRAFT"

    def test_single_row_bordereau_submittable(self, api):
        """PRD §3.7: "the bordereau must contain at least one row
        (`ERR_EMPTY_BORDEREAU`)" — crossing from zero rows to one row makes
        the same bordereau submittable (the zero-count boundary from below).

        Design: Difficulty/boundary_precision_check/empty_bordereau_zero_rows_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = _bound_policy(api, program, "Row Co")
        bor = _draft_premium_bordereau(
            api, program,
            [{"policy_id": policy["id"], "written_premium_cents": 155000,
              "commission_cents": 23250}],
            {"premium_cents": 155000, "commission_cents": 23250})
        submitted = validate_success(api.submit_bordereau(bor["id"], FIN))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["row_count"] == 1

    def test_duplicate_row_rejected(self, api):
        """PRD §3.7: "no `policy_id` (on a `PREMIUM` bordereau) or `claim_id`
        (on a `CLAIMS` bordereau) may repeat within `rows`
        (`ERR_BORDEREAU_DUPLICATE_ROW`)."

        Design: Corner/calculations/bordereau_duplicate_row_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = _bound_policy(api, program, "Dup Row")
        row = {"policy_id": policy["id"], "written_premium_cents": 155000,
               "commission_cents": 23250}
        bor = _draft_premium_bordereau(
            api, program, [row, dict(row)],
            {"premium_cents": 310000, "commission_cents": 46500})
        resp = api.submit_bordereau(bor["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_BORDEREAU_DUPLICATE_ROW)

    def test_unknown_policy_row_rejected(self, api):
        """PRD §3.7: "every referenced policy or claim must exist and belong
        to this program (`ERR_BORDEREAU_ROW_UNKNOWN_POLICY`)."

        Design: Corner/calculations/bordereau_unknown_policy_row_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        bor = _draft_premium_bordereau(
            api, program,
            [{"policy_id": NON_EXISTENT_UUID, "written_premium_cents": 1000,
              "commission_cents": 150}],
            {"premium_cents": 1000, "commission_cents": 150})
        resp = api.submit_bordereau(bor["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_BORDEREAU_ROW_UNKNOWN_POLICY)

    def test_row_amount_mismatch_rejected(self, api):
        """PRD §3.7: "every row's amounts must equal the referenced entity's
        current fields — for `PREMIUM`, the policy's `gross_premium_cents` and
        `mga_commission_cents`, for `CLAIMS`, the claim's `paid_cents` and
        `case_reserve_cents` (`ERR_BORDEREAU_ROW_MISMATCH`)."

        Design: Corner/calculations/bordereau_row_amount_mismatch_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = _bound_policy(api, program, "Row Bad")  # gross 155000
        bor = _draft_premium_bordereau(
            api, program,
            [{"policy_id": policy["id"], "written_premium_cents": 150000,
              "commission_cents": 22500}],
            {"premium_cents": 150000, "commission_cents": 22500})
        resp = api.submit_bordereau(bor["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_BORDEREAU_ROW_MISMATCH)

    def test_period_already_covered_rejected(self, api):
        """PRD §3.7: "no other bordereau of the same program, `bordereau_type`,
        and `period_label` may already be `ACCEPTED`
        (`ERR_BORDEREAU_PERIOD_COVERED`)."

        Design: Corner/calculations/bordereau_period_already_covered_rejected
        """
        carrier, program, _g, _a, _f = setup_active_program()
        policy = _bound_policy(api, program, "Period Co")
        rows = [{"policy_id": policy["id"], "written_premium_cents": 155000,
                 "commission_cents": 23250}]
        totals = {"premium_cents": 155000, "commission_cents": 23250}
        bor1 = _draft_premium_bordereau(api, program, rows, totals)
        validate_success(api.submit_bordereau(bor1["id"], FIN))
        cu = make_carrier_underwriter_headers(carrier["id"])
        accepted = validate_success(api.accept_bordereau(bor1["id"], cu))
        assert accepted["status"] == "ACCEPTED"

        bor2 = _draft_premium_bordereau(api, program, rows, totals)
        resp = api.submit_bordereau(bor2["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_BORDEREAU_PERIOD_COVERED)

    def test_accept_marks_policy_reported(self, api):
        """PRD §3.7: "Acceptance (`SUBMITTED → ACCEPTED`) marks the underlying
        records as reported: on a `PREMIUM` bordereau each referenced policy's
        `reported_premium_bordereau_id` is set to the accepting bordereau."

        Design: Corner/calculations/bordereau_period_already_covered_rejected
        """
        carrier, program, _g, _a, _f = setup_active_program()
        policy = _bound_policy(api, program, "Marked Co")
        bor = _draft_premium_bordereau(
            api, program,
            [{"policy_id": policy["id"], "written_premium_cents": 155000,
              "commission_cents": 23250}],
            {"premium_cents": 155000, "commission_cents": 23250})
        validate_success(api.submit_bordereau(bor["id"], FIN))
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.accept_bordereau(bor["id"], cu))
        fresh = get_policy_fresh(policy["id"])
        assert fresh["reported_premium_bordereau_id"] == bor["id"]


class TestBordereauRevisionLoop:
    def test_reject_revise_resubmit_cycle(self, api):
        """PRD §3.7: "Rejection (`SUBMITTED → REJECTED`) requires a non-empty
        `rejection_reason`, which is stored. The MGA finance desk may revise a
        rejected bordereau back to `DRAFT`, clearing `rejection_reason` and
        resetting `submitted_at` to null; the draft–submit–reject–revise loop
        is unbounded."

        Design: Corner/state_machines/bordereau_reject_revise_resubmit_cycle
        """
        carrier, program, _g, _a, _f = setup_active_program()
        policy = _bound_policy(api, program, "Cycle Co")
        bor = _draft_premium_bordereau(
            api, program,
            [{"policy_id": policy["id"], "written_premium_cents": 155000,
              "commission_cents": 23250}],
            {"premium_cents": 155000, "commission_cents": 23250})
        validate_success(api.submit_bordereau(bor["id"], FIN))

        cu = make_carrier_underwriter_headers(carrier["id"])
        rejected = validate_success(api.reject_bordereau(
            bor["id"], {"rejection_reason": "missing schedule page"}, cu))
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "missing schedule page"

        revised = validate_success(api.revise_bordereau(bor["id"], FIN))
        assert revised["status"] == "DRAFT"
        assert revised["rejection_reason"] is None
        assert revised["submitted_at"] is None

        resubmitted = validate_success(api.submit_bordereau(bor["id"], FIN))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["id"] == bor["id"]
