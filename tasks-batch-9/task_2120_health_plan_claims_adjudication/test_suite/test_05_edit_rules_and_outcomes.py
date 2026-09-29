"""Edit rules, authorization matching, and the six-step claim-level outcome resolution."""
import pytest

from test_helpers import (
    adjudicate,
    claim_line_payload,
    finalize,
    get_accumulator,
    get_authorization,
    get_coverage_rows,
    get_remittances,
    lines_by_number,
    override_claim,
    publish_edit_rule,
    setup_authorization_units_boundary,
    setup_claim_outside_every_coverage_interval,
    setup_denied_no_coverage_claim,
    setup_open_plan_environment,
    setup_pended_auth_units_exceeded_claim,
    setup_revoked_authorization_claim,
    submit_and_adjudicate,
)


class TestAuthorizationRemainingUnitsBoundary:
    def test_remaining_units_exactly_equal_to_the_line_units_still_price(self, api):
        """PRD §3.6: "3. The selected grant's remaining units — its `authorized_units` less
        its `units_consumed` — are fewer than the line's `units` — the line moves
        `PENDING → PENDED` with `edit_reason_code` set to `PEND_AUTH_UNITS_EXCEEDED`.
        Remaining units **exactly equal** to the line's `units` are sufficient and do not
        pend; the test is strictly fewer-than."

        Design: Difficulty/boundary_precision_check/authorization_remaining_units_exactly_equal_prices_but_one_more_pends
        """
        env = setup_authorization_units_boundary()
        exact = adjudicate(env["exact_units_claim"]["id"])
        assert exact["status"] == "ADJUDICATED", (
            "Two remaining units satisfy a two-unit line exactly"
        )
        assert exact["total_allowed_cents"] == 61000

        authorization = get_authorization(env["authorization"]["id"])
        assert authorization["units_consumed"] == 4
        assert authorization["status"] == "EXHAUSTED"

    def test_one_unit_beyond_the_remaining_grant_pends_the_claim(self, api):
        """PRD §3.6: "3. The selected grant's remaining units — its `authorized_units` less
        its `units_consumed` — are fewer than the line's `units` — the line moves
        `PENDING → PENDED` with `edit_reason_code` set to `PEND_AUTH_UNITS_EXCEEDED`."
        PRD §3.6: "A pended line also keeps `allowed_amount_cents` at zero, leaves
        `authorization_id` null, and consumes nothing."

        Design: Difficulty/boundary_precision_check/authorization_remaining_units_exactly_equal_prices_but_one_more_pends
        """
        env = setup_authorization_units_boundary()
        adjudicate(env["exact_units_claim"]["id"])
        over = adjudicate(env["over_units_claim"]["id"])
        assert over["status"] == "PENDED"
        assert over["pend_reason_code"] == "PEND_AUTH_UNITS_EXCEEDED"
        assert over["total_allowed_cents"] == 0

        line = lines_by_number(over["id"])[1]
        assert line["line_status"] == "PENDED"
        assert line["allowed_amount_cents"] == 0
        assert line["authorization_id"] is None


class TestCoverageGateOnAdjudication:
    def test_no_segment_containing_the_service_date_leaves_coverage_id_null(self, api):
        """PRD §3.4: "A segment is a candidate when its `effective_date` falls on or before
        that earliest service date and either its `term_date` is null or its `term_date`
        falls strictly after that earliest service date."
        PRD §3.4: "When no candidate exists, `coverage_id` stays null."

        Design: Difficulty/cross_entity_state_dependency/claim_denies_when_no_member_coverage_interval_contains_service_date
        """
        env = setup_claim_outside_every_coverage_interval()
        claim = env["claim_at_intake"]
        assert claim["coverage_id"] is None, (
            "The half-open segment [2026-01-01, 2026-02-01) excludes a 2026-02-10 service date"
        )
        assert claim["cob_role"] == "PRIMARY"
        assert claim["status"] == "RECEIVED"

    def test_a_line_no_segment_covers_denies_the_claim_with_no_coverage(self, api):
        """PRD §3.8: "2. **No coverage.** If the coverage gate fails, the claim's `status`
        becomes `DENIED` with `deny_reason_code` set to `DENY_NO_COVERAGE`. The gate is
        evaluated per line using the same half-open arithmetic as intake matching: a line is
        covered when some coverage segment of the claim's member has an `effective_date` on
        or before that line's `service_date` and either a null `term_date` or a `term_date`
        strictly after it. The claim is covered only when **every** line is covered."

        Design: Difficulty/cross_entity_state_dependency/claim_denies_when_no_member_coverage_interval_contains_service_date
        """
        env = setup_claim_outside_every_coverage_interval()
        claim = adjudicate(env["claim_at_intake"]["id"])
        assert claim["status"] == "DENIED"
        assert claim["deny_reason_code"] == "DENY_NO_COVERAGE"
        assert claim["total_allowed_cents"] == 0
        assert claim["total_plan_paid_cents"] == 0

        coverage_rows = get_coverage_rows(env["member"]["id"])
        assert len(coverage_rows) == 1
        assert coverage_rows[0]["status"] == "ACTIVE", (
            "The segment was never terminated; only its date range decided the outcome"
        )


class TestRevokedAuthorizationMatching:
    def test_a_revoked_grant_pends_the_claim_with_the_revoked_reason(self, api):
        """PRD §3.6: "2. The selected grant's `status` is `REVOKED` — the line moves
        `PENDING → PENDED` with `edit_reason_code` set to `PEND_AUTH_REVOKED`."
        PRD §3.3: "Service lines that later match a revoked grant pend with
        `PEND_AUTH_REVOKED` instead of pricing."

        Design: Difficulty/cross_entity_state_dependency/claim_line_pends_when_matched_authorization_is_revoked
        """
        env = setup_revoked_authorization_claim()
        assert env["revoked_authorization"]["status"] == "REVOKED"

        claim = adjudicate(env["claim_at_intake"]["id"])
        assert claim["status"] == "PENDED"
        assert claim["pend_reason_code"] == "PEND_AUTH_REVOKED"

    def test_a_line_pended_on_a_revoked_grant_consumes_nothing(self, api):
        """PRD §3.6: "Note carefully that in the three pend outcomes the line's
        `edit_reason_code` carries the **derived** authorization code — `PEND_AUTH_MISSING`,
        `PEND_AUTH_REVOKED` or `PEND_AUTH_UNITS_EXCEEDED` — and **not** the `AUTH_REQUIRED`
        rule's own `reason_code`."
        PRD §3.6: "A pended line also keeps `allowed_amount_cents` at zero, leaves
        `authorization_id` null, and consumes nothing."

        Design: Difficulty/cross_entity_state_dependency/claim_line_pends_when_matched_authorization_is_revoked
        """
        env = setup_revoked_authorization_claim()
        claim = adjudicate(env["claim_at_intake"]["id"])

        line = lines_by_number(claim["id"])[1]
        assert line["line_status"] == "PENDED"
        assert line["edit_reason_code"] == "PEND_AUTH_REVOKED"
        assert line["authorization_id"] is None
        assert line["allowed_amount_cents"] == 0

        authorization = get_authorization(env["authorization"]["id"])
        assert authorization["units_consumed"] == 0, (
            "A revoked authorization is never consumed"
        )


class TestClaimLevelOutcomeResolution:
    def test_a_hard_deny_outranks_a_pend_while_a_soft_deny_does_not(self, api):
        """PRD §3.8: "1. **Hard denials.** Gather the lines whose `edit_reason_code` came
        from a rule with `severity` `DENY` and `precedence_rank` of 10 or lower. If that set
        is non-empty, the claim's `status` becomes `DENIED` and its `deny_reason_code` takes
        the `reason_code` of the hard-deny rule with the lowest `precedence_rank`, with ties
        broken by the affected line's `line_number` ascending."
        PRD §3.8: "4. **Pended lines.** If any line ended at `PENDED`, the claim's `status`
        becomes `PENDED` and its `pend_reason_code` takes the `edit_reason_code` of the
        pended line whose triggering rule has the lowest `precedence_rank`, with ties broken
        by `line_number` ascending. This test deliberately sits **ahead** of the next one,
        which is why a soft denial — a `DENY`-severity rule with a `precedence_rank` above
        10 — never masks a pend."

        Design: Corner/calculations/hard_deny_rank_outranks_a_pend_but_a_soft_deny_does_not
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "PREC-1", "name": "Precedence Plan"},
            provider_overrides={"npi": "2000000020", "name": "Psi Surgical"},
            member_overrides={"member_number": "M-PREC-1"},
            rates=[
                ("97110", 5000, "2026-01-01"),
                ("73721", 40000, "2026-01-01"),
                ("29881", 90000, "2026-01-01"),
                ("29880", 80000, "2026-01-01"),
            ],
        )
        publish_edit_rule(
            rule_code="UL-97110",
            edit_type="UNITS_LIMIT",
            primary_code="97110",
            max_units=4,
            severity="DENY",
            precedence_rank=25,
            reason_code="DENY_UNITS_EXCEEDED",
        )
        publish_edit_rule(
            rule_code="MP-73721-AUTH-P",
            edit_type="AUTH_REQUIRED",
            primary_code="73721",
            severity="PEND",
            precedence_rank=30,
            reason_code="PEND_AUTH_MISSING",
        )
        publish_edit_rule(
            rule_code="EXCL-29881",
            edit_type="MUTUALLY_EXCLUSIVE",
            primary_code="29881",
            secondary_code="29880",
            severity="DENY",
            precedence_rank=5,
            reason_code="DENY_MUTUALLY_EXCLUSIVE",
        )

        soft = submit_and_adjudicate(
            env,
            [
                claim_line_payload(1, "97110", 6, 30000, "2026-02-10"),
                claim_line_payload(2, "73721", 1, 60000, "2026-02-10"),
            ],
            "CLM-PREC-A",
        )
        assert soft["status"] == "PENDED", "A rank-25 denial never masks a pend"
        assert soft["pend_reason_code"] == "PEND_AUTH_MISSING"
        assert soft["deny_reason_code"] is None
        assert lines_by_number(soft["id"])[1]["line_status"] == "DENIED"
        assert lines_by_number(soft["id"])[1]["edit_reason_code"] == "DENY_UNITS_EXCEEDED"

        hard = submit_and_adjudicate(
            env,
            [
                claim_line_payload(1, "29881", 1, 100000, "2026-02-11"),
                claim_line_payload(2, "29880", 1, 90000, "2026-02-11"),
                claim_line_payload(3, "73721", 1, 60000, "2026-02-11"),
            ],
            "CLM-PREC-B",
        )
        assert hard["status"] == "DENIED", "A rank-5 denial outranks every pend on the claim"
        assert hard["deny_reason_code"] == "DENY_MUTUALLY_EXCLUSIVE"
        assert hard["pend_reason_code"] is None
        hard_lines = lines_by_number(hard["id"])
        assert hard_lines[2]["line_status"] == "DENIED"
        assert hard_lines[2]["edit_reason_code"] == "DENY_MUTUALLY_EXCLUSIVE"
        assert hard_lines[1]["line_status"] == "PRICED"

    def test_a_bundling_rule_folds_the_secondary_line_into_the_surviving_one(self, api):
        """PRD §3.6: "A **`BUNDLING`** rule fires on a line when the rule's `secondary_code`
        equals the line's `procedure_code` *and* another line of the same claim carrying the
        same `service_date` has a `procedure_code` equal to the rule's `primary_code`. The
        line moves `PENDING → BUNDLED`: its `allowed_amount_cents`, `member_liability_cents`
        and `plan_paid_cents` are all set to zero, its `bundled_into_line_number` records the
        `line_number` of the surviving line it folded into, and its `edit_reason_code` takes
        the rule's `reason_code`."
        PRD §3.5: "The claim's `total_allowed_cents` is then the sum of the already-rounded
        per-line `allowed_amount_cents` over the lines whose `line_status` is `PRICED` or
        `PAID`; lines that ended `BUNDLED`, `DENIED` or `PENDED` contribute nothing and are
        excluded from the total."

        Design: Corner/calculations/bundling_edit_zeroes_the_secondary_line_and_records_bundled_into_line_number
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "BUND-1", "name": "Bundling Plan"},
            provider_overrides={"npi": "2000000019", "name": "Chi Lab"},
            member_overrides={"member_number": "M-BUND-1"},
            rates=[("80053", 6000, "2026-01-01"), ("82947", 3333, "2026-01-01")],
        )
        publish_edit_rule(
            rule_code="NCCI-BUNDLE-1",
            edit_type="BUNDLING",
            primary_code="80053",
            secondary_code="82947",
            severity="DENY",
            precedence_rank=40,
            reason_code="DENY_BUNDLED_INTO_PRIMARY",
        )
        claim = submit_and_adjudicate(
            env,
            [
                claim_line_payload(1, "80053", 1, 10000, "2026-02-10"),
                claim_line_payload(2, "82947", 1, 5000, "2026-02-10"),
            ],
            "CLM-BUND-1",
        )
        assert claim["status"] == "ADJUDICATED"
        assert claim["total_allowed_cents"] == 6000

        lines = lines_by_number(claim["id"])
        assert lines[1]["line_status"] == "PRICED"
        assert lines[1]["allowed_amount_cents"] == 6000
        assert lines[2]["line_status"] == "BUNDLED"
        assert lines[2]["allowed_amount_cents"] == 0
        assert lines[2]["member_liability_cents"] == 0
        assert lines[2]["plan_paid_cents"] == 0
        assert lines[2]["bundled_into_line_number"] == 1
        assert lines[2]["edit_reason_code"] == "DENY_BUNDLED_INTO_PRIMARY"

    def test_a_wholly_denied_claim_takes_the_lowest_line_numbers_reason(self, api):
        """PRD §3.8: "5. **Everything knocked out.** If every line ended `DENIED` or
        `BUNDLED`, the claim's `status` becomes `DENIED`. Its `deny_reason_code` takes the
        `edit_reason_code` of the denied line with the lowest `line_number`; when the claim
        has no denied line at all because every line was bundled away, the code is
        `DENY_BUNDLED_ALL` instead."
        PRD §3.5: "If no rate survives that filter, the line is not priced at all: it moves
        `PENDING → DENIED`, its `allowed_amount_cents` is set to zero, and its
        `edit_reason_code` is stamped `DENY_NON_COVERED_SERVICE`."

        Design: Corner/calculations/claim_with_every_line_denied_takes_the_lowest_line_number_reason
        """
        env = setup_open_plan_environment(
            plan_overrides={"plan_code": "ALLD-1", "name": "All Denied Plan"},
            provider_overrides={"npi": "2000000021", "name": "Omega Rehab"},
            member_overrides={"member_number": "M-ALLD-1"},
            rates=[("97110", 5000, "2026-01-01")],
        )
        publish_edit_rule(
            rule_code="UL-97110-B",
            edit_type="UNITS_LIMIT",
            primary_code="97110",
            max_units=4,
            severity="DENY",
            precedence_rank=25,
            reason_code="DENY_UNITS_EXCEEDED",
        )
        claim = submit_and_adjudicate(
            env,
            [
                claim_line_payload(1, "97110", 6, 30000, "2026-02-10"),
                claim_line_payload(2, "99999", 1, 15000, "2026-02-10"),
            ],
            "CLM-ALLD-1",
        )
        assert claim["status"] == "DENIED"
        assert claim["deny_reason_code"] == "DENY_UNITS_EXCEEDED", (
            "The lowest-numbered denied line decides the claim's reason code"
        )
        assert claim["total_allowed_cents"] == 0
        assert lines_by_number(claim["id"])[2]["edit_reason_code"] == "DENY_NON_COVERED_SERVICE"


class TestMedicalDirectorOverrideEffects:
    def test_an_approve_override_consumes_units_beyond_the_granted_amount(self, api):
        """PRD §3.8: "An `APPROVE` decision moves the claim `PENDED → ADJUDICATED` and forces
        every line standing at `PENDED` through `PENDED → PRICED`, computing its allowed
        amount and cost share exactly as a normal pass would but **bypassing the
        `AUTH_REQUIRED` edit entirely**."
        PRD §3.8: "If that relaxed search finds a grant, the line's `authorization_id` is set
        to it and that grant's `units_consumed` increases by the line's `units` — **even when
        doing so drives `units_consumed` above `authorized_units`**, at which point the grant
        re-derives to `EXHAUSTED`."

        Design: Corner/state_machines/override_approve_consumes_authorization_units_beyond_the_granted_amount
        """
        env = setup_pended_auth_units_exceeded_claim()
        assert env["claim"]["status"] == "PENDED"
        assert env["claim"]["pend_reason_code"] == "PEND_AUTH_UNITS_EXCEEDED"

        released = override_claim(env["claim"]["id"], "APPROVE", user_id="u-md-8")
        assert released["status"] == "ADJUDICATED"
        assert released["pend_reason_code"] is None
        assert released["total_allowed_cents"] == 120000

        authorization = get_authorization(env["authorization"]["id"])
        assert authorization["units_consumed"] == 3, (
            "Three units are consumed against a one-unit grant"
        )
        assert authorization["status"] == "EXHAUSTED"

        line = lines_by_number(env["claim"]["id"])[1]
        assert line["line_status"] == "PRICED"
        assert line["authorization_id"] == env["authorization"]["id"]


class TestDeniedClaimFinalization:
    def test_finalizing_a_denied_claim_issues_a_zero_pay_remittance_and_posts_nothing(
        self, api
    ):
        """PRD §3.9: "From `DENIED`, finalizing applies `DENIED → FINALIZED` and behaves
        differently in exactly one respect that must not be overlooked. A zero-pay
        remittance advice is still created, in `status` `ISSUED`, with `total_plan_paid_cents`
        of 0, and the claim's `payment_status` still flips `NOT_REMITTED → REMITTED`, and a
        `FINALIZE` event is still appended — but **no benefit accumulator field moves at
        all** and `remitted_claim_count` is **not** incremented."

        Design: Corner/state_machines/finalizing_a_denied_claim_issues_zero_pay_remittance_without_touching_accumulator
        """
        env = setup_denied_no_coverage_claim(claim_number="CLM-SM-7")
        assert env["claim"]["status"] == "DENIED"
        assert env["claim"]["deny_reason_code"] == "DENY_NO_COVERAGE"

        finalized = finalize(env["claim"]["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["payment_status"] == "REMITTED"

        remittances = get_remittances(env["claim"]["id"])
        assert len(remittances) == 1
        assert remittances[0]["status"] == "ISSUED"
        assert remittances[0]["total_plan_paid_cents"] == 0

        accumulator = get_accumulator(env["member"]["id"])
        assert accumulator["deductible_applied_cents"] == 0
        assert accumulator["oop_applied_cents"] == 0
        assert accumulator["remitted_claim_count"] == 0
