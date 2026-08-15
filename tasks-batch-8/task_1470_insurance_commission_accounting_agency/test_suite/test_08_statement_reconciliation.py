"""Carrier statement reconciliation: matching tolerance, pinned rounding,
dispute rework cycle, close preconditions, and closed-interval periods
(PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    bind_policy,
    create_carrier,
    create_policy,
    create_producer,
    create_product,
    create_schedule,
    create_statement,
    deliver_policy_disclosure,
    find_line,
    get_single_entry,
    setup_bound_policy,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestStatementPeriodOverlap:
    """Difficulty instance: statement periods are closed intervals — a shared
    boundary date already counts as overlap."""

    def test_shared_boundary_date_overlaps(self):
        """PRD §3.7: "Two statements of the same carrier whose closed
        intervals intersect — and a shared boundary date counts as an
        intersection — are rejected with `ERR_STATEMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/statement_closed_interval_overlap
        """
        carrier = create_carrier(name="Carrier I", carrier_code="CI")
        create_statement(
            carrier["id"], [], period_start="2026-01-01", period_end="2026-01-31"
        )
        res = api_client.create_carrier_statement(
            {
                "carrier_id": carrier["id"],
                "period_start": "2026-01-31",
                "period_end": "2026-02-28",
                "lines": [],
            },
            ADMIN,
        )
        validate_error(
            res, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP, expected_status=409
        )

    def test_next_day_period_accepted(self):
        """PRD §3.7: "An `AgencyAdmin` or `AgencyAccountant` imports a
        **CarrierStatement** by supplying the `carrier_id`, a `period_start`
        (inclusive) and `period_end` (inclusive — the period is a closed
        interval), and the statement's `lines`, an array whose elements each
        carry a `line_ref` holding a policy number and a
        `reported_amount_cents`. Two statements of the same carrier whose
        closed intervals intersect — and a shared boundary date counts as an
        intersection — are rejected with `ERR_STATEMENT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/statement_closed_interval_overlap
        """
        carrier = create_carrier(name="Carrier I", carrier_code="CI")
        create_statement(
            carrier["id"], [], period_start="2026-01-01", period_end="2026-01-31"
        )
        validate_error(
            api_client.create_carrier_statement(
                {
                    "carrier_id": carrier["id"],
                    "period_start": "2026-01-31",
                    "period_end": "2026-02-28",
                    "lines": [],
                },
                ADMIN,
            ),
            ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP,
            expected_status=409,
        )
        ok = validate_success(
            api_client.create_carrier_statement(
                {
                    "carrier_id": carrier["id"],
                    "period_start": "2026-02-01",
                    "period_end": "2026-02-28",
                    "lines": [],
                },
                ADMIN,
            ),
            201,
        )
        assert ok["status"] == "RECEIVED"


class TestDisputeResumeCycle:
    """Difficulty instance: RECONCILING -> DISPUTED -> RECONCILING repeats
    without bound."""

    def _reconciling_statement(self):
        carrier = create_carrier(name="Carrier D", carrier_code="CD")
        statement = create_statement(
            carrier["id"], [], period_start="2026-08-01", period_end="2026-08-31"
        )
        started = validate_success(
            api_client.start_reconciliation(statement["id"], ADMIN), 200
        )
        assert started["status"] == "RECONCILING"
        return statement["id"]

    def test_dispute_then_resume_closes_cycle(self):
        """PRD §3.7: "Reconciliation supports a rework cycle: a statement in
        `RECONCILING` may be flagged as `DISPUTED`, and a disputed statement
        may resume to `RECONCILING`; the pair may repeat without bound while
        differences are argued with the carrier."

        Design: Difficulty/non_linear_state_machine/statement_dispute_resume_cycle
        """
        statement_id = self._reconciling_statement()
        disputed = validate_success(
            api_client.dispute_statement(statement_id, ADMIN), 200
        )
        assert disputed["status"] == "DISPUTED"
        resumed = validate_success(
            api_client.resume_statement(statement_id, ADMIN), 200
        )
        assert resumed["status"] == "RECONCILING"

    def test_cycle_is_repeatable(self):
        """PRD §3.7: "Reconciliation supports a rework cycle: a statement in
        `RECONCILING` may be flagged as `DISPUTED`, and a disputed statement
        may resume to `RECONCILING`; the pair may repeat without bound while
        differences are argued with the carrier."

        Design: Difficulty/non_linear_state_machine/statement_dispute_resume_cycle
        """
        statement_id = self._reconciling_statement()
        for _ in range(2):
            disputed = validate_success(
                api_client.dispute_statement(statement_id, ADMIN), 200
            )
            assert disputed["status"] == "DISPUTED"
            resumed = validate_success(
                api_client.resume_statement(statement_id, ADMIN), 200
            )
            assert resumed["status"] == "RECONCILING"


class TestStatementInvalidTransitions:
    def test_close_from_received_rejected(self):
        """PRD §3.7: "Closing reconciliation — moving the statement from
        `RECONCILING` to `RECONCILED` — is permitted only when every line's
        `match_status` is `MATCHED` or `WAIVED` and no commission entry
        linked to this statement remains in `VARIANCE`; otherwise the close
        is rejected with `ERR_UNMATCHED_STATEMENT_LINES`."
        PRD §2.9: "4. **State admissibility** — the target resource is in a
        state that allows the operation, and the optimistic-concurrency check
        of §2.7 passes, else `ERR_INVALID_STATE` or `ERR_STALE_VERSION`."

        Design: Corner/state_machines/statement_close_from_received_returns_409
        """
        carrier = create_carrier(name="Carrier S4C", carrier_code="CS4C")
        statement = create_statement(carrier["id"], [])
        assert statement["status"] == "RECEIVED"
        res = api_client.close_statement(statement["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_resume_from_reconciling_rejected(self):
        """PRD §3.7: "a statement in `RECONCILING` may be flagged as
        `DISPUTED`, and a disputed statement may resume to `RECONCILING`".

        Design: Corner/state_machines/statement_resume_from_reconciling_returns_409
        """
        carrier = create_carrier(name="Carrier S5C", carrier_code="CS5C")
        statement = create_statement(carrier["id"], [])
        validate_success(api_client.start_reconciliation(statement["id"], ADMIN), 200)
        res = api_client.resume_statement(statement["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestPerEntryRoundingThenSum:
    """Difficulty instance: statement totals sum per-entry rounded amounts —
    never a single rounding after summation."""

    def _setup_two_rounded_entries(self):
        producer = create_producer(
            name="Writer R", license_number="LIC-R1", tax_form_on_file=True
        )
        carrier = create_carrier(name="Carrier R", carrier_code="CR")
        product = create_product(carrier["id"], product_code="PR")
        create_schedule(
            product["id"],
            tier="STANDARD",
            commission_rate_bps=5000,
            override_rate_bps=0,
            advance_months=12,
            effective_from="2026-01-01",
        )
        policies = []
        for number in ("P-R1", "P-R2"):
            policy = create_policy(
                product["id"],
                producer["id"],
                policy_number=number,
                billing_type="DIRECT_BILL",
                premium_annual_cents=99995,
                effective_date="2026-08-01",
            )
            deliver_policy_disclosure(policy["id"])
            bind_policy(policy["id"])
            policies.append(policy)
        statement = create_statement(
            carrier["id"],
            [
                {"line_ref": "P-R1", "reported_amount_cents": 49998},
                {"line_ref": "P-R2", "reported_amount_cents": 49998},
            ],
        )
        started = validate_success(
            api_client.start_reconciliation(statement["id"], ADMIN), 200
        )
        return policies, started

    def test_each_entry_rounded_half_up_at_creation(self):
        """PRD §2.6: "Rounding is pinned to the individual commission entry
        at creation time: each entry's booked amount is rounded half-up when
        the entry is created, and any later total that aggregates entries —
        most notably the statement totals in §3.7 — sums those per-entry
        rounded integer values."
        PRD §3.3: "first the full first-year amount is computed as the
        policy's `premium_annual_cents` multiplied by the schedule's
        `commission_rate_bps` and divided by 10000, rounded half-up to whole
        cents."

        Design: Difficulty/combinatorial_formula/per_entry_rounding_then_sum
        """
        policies, _ = self._setup_two_rounded_entries()
        for policy in policies:
            entry = get_single_entry(policy["id"], "BASE")
            # 99995 * 5000 / 10000 = 49997.5 -> round half up -> 49998.
            assert entry["amount_cents"] == 49998
            assert entry["status"] == "MATCHED"

    def test_statement_totals_sum_per_entry_rounded_values(self):
        """PRD §3.7: "Statement totals then fall out per §2.6's pinned
        rounding: `matched_total_cents` sums the reported amounts of
        `MATCHED` lines, `expected_matched_total_cents` sums the booked
        amounts of the linked entries — the per-entry rounded integers, never
        a rounding applied after summation — and `variance_total_cents` is
        `matched_total_cents` minus `expected_matched_total_cents`."

        Design: Difficulty/combinatorial_formula/per_entry_rounding_then_sum
        """
        _, started = self._setup_two_rounded_entries()
        # 49998 + 49998 = 99996 (per-entry round then sum); the sum-then-
        # round order would wrongly yield 99995.
        assert started["expected_matched_total_cents"] == 99996
        assert started["matched_total_cents"] == 99996
        assert started["variance_total_cents"] == 0


class TestToleranceBoundary:
    def test_delta_100_matches_delta_101_variances(self):
        """PRD §3.7: "when the absolute difference is no more than one dollar
        — 100 cents — the entry moves from `EXPECTED` to `MATCHED` with
        `matched_statement_id` set to this statement and `matched_at`
        stamped, and the line is marked `MATCHED`; when the difference
        exceeds that tolerance, the entry moves to `VARIANCE` with its
        `matched_statement_id` set, and the line is marked
        `VARIANCE_FLAGGED`."

        Design: Corner/calculations/tolerance_boundary_100_matched_101_variance
        """
        producer = create_producer(name="Tol T", license_number="LIC-C1T")
        carrier = create_carrier(name="Carrier C1T", carrier_code="CC1T")
        product = create_product(carrier["id"], product_code="PC1T")
        create_schedule(product["id"], commission_rate_bps=5000)
        policies = {}
        for number in ("P-TA", "P-TB"):
            policy = create_policy(
                product["id"],
                producer["id"],
                policy_number=number,
                premium_annual_cents=2400000,
            )
            deliver_policy_disclosure(policy["id"])
            bind_policy(policy["id"])
            policies[number] = policy
        statement = create_statement(
            carrier["id"],
            [
                {"line_ref": "P-TA", "reported_amount_cents": 1200100},
                {"line_ref": "P-TB", "reported_amount_cents": 1200101},
            ],
        )
        validate_success(api_client.start_reconciliation(statement["id"], ADMIN), 200)

        entry_a = get_single_entry(policies["P-TA"]["id"], "BASE")
        entry_b = get_single_entry(policies["P-TB"]["id"], "BASE")
        # |1200100 - 1200000| = 100 <= tolerance -> MATCHED.
        assert entry_a["status"] == "MATCHED"
        assert entry_a["matched_statement_id"] == statement["id"]
        # |1200101 - 1200000| = 101 > tolerance -> VARIANCE.
        assert entry_b["status"] == "VARIANCE"
        assert entry_b["matched_statement_id"] == statement["id"]


class TestCloseZeroUnresolvedBoundary:
    """Difficulty instance: close requires the unresolved-line count to be
    exactly zero; waiving the single ORPHAN line unlocks the close."""

    def _setup_statement_with_orphan(self):
        bundle = setup_bound_policy(
            premium_annual_cents=2400000,
            commission_rate_bps=5000,
            policy_number="P-Z1",
        )
        statement = create_statement(
            bundle["carrier"]["id"],
            [
                {"line_ref": "P-Z1", "reported_amount_cents": 1200000},
                {"line_ref": "GHOST-1", "reported_amount_cents": 5000},
            ],
        )
        started = validate_success(
            api_client.start_reconciliation(statement["id"], ADMIN), 200
        )
        return bundle, started

    def test_orphan_line_blocks_close(self):
        """PRD §3.7: "Closing reconciliation — moving the statement from
        `RECONCILING` to `RECONCILED` — is permitted only when every line's
        `match_status` is `MATCHED` or `WAIVED` and no commission entry
        linked to this statement remains in `VARIANCE`; otherwise the close
        is rejected with `ERR_UNMATCHED_STATEMENT_LINES`."
        PRD §3.7: "If no candidate exists, the line is marked `ORPHAN`."

        Design: Difficulty/boundary_precision_check/statement_close_zero_unresolved_boundary
        """
        _, started = self._setup_statement_with_orphan()
        assert find_line(started, "P-Z1")["match_status"] == "MATCHED"
        assert find_line(started, "GHOST-1")["match_status"] == "ORPHAN"
        res = api_client.close_statement(started["id"], ADMIN)
        validate_error(
            res, ApiErrorId.ERR_UNMATCHED_STATEMENT_LINES, expected_status=409
        )

    def test_waiving_last_orphan_allows_close(self):
        """PRD §3.7: "Separately, an `AgencyAdmin` may waive an `ORPHAN` line
        by naming its `line_ref`, moving the line to `WAIVED`."
        PRD §3.7: "Closing reconciliation — moving the statement from
        `RECONCILING` to `RECONCILED` — is permitted only when every line's
        `match_status` is `MATCHED` or `WAIVED` and no commission entry
        linked to this statement remains in `VARIANCE`; otherwise the close
        is rejected with `ERR_UNMATCHED_STATEMENT_LINES`."

        Design: Difficulty/boundary_precision_check/statement_close_zero_unresolved_boundary
        """
        _, started = self._setup_statement_with_orphan()
        validate_error(
            api_client.close_statement(started["id"], ADMIN),
            ApiErrorId.ERR_UNMATCHED_STATEMENT_LINES,
            expected_status=409,
        )
        waived = validate_success(
            api_client.waive_statement_line(
                started["id"], {"line_ref": "GHOST-1"}, ADMIN
            ),
            200,
        )
        assert find_line(waived, "GHOST-1")["match_status"] == "WAIVED"
        closed = validate_success(api_client.close_statement(started["id"], ADMIN), 200)
        assert closed["status"] == "RECONCILED"
