"""Trust accounting: collections, remittance computation (both holdback tiers,
pinned evaluation order), ledger immutability, derived-field reconciliation,
and the final-audit premium variant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_ledger_entry,
    bind_policy,
    collect_premium,
    create_issued_policy,
    get_policy_fresh,
    get_program_fresh,
    issue_policy,
    list_ledger,
    quote_policy,
    setup_active_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]


class TestCollectionsAndLedger:
    def test_partial_collections_reconcile_derived_fields(self, api):
        """PRD §3.5: "the platform posts a `COLLECTION` TrustLedgerEntry for
        the positive amount with the policy's `policy_id` set, grows the
        policy's `collected_cents` by the same amount, and grows the program's
        `trust_balance_cents` by it too, storing the resulting balance as the
        entry's `running_balance_cents`."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_partial_collections
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Derived Co")
        policy = bind_policy(policy)

        e1 = collect_premium(policy, 100000)
        assert e1["running_balance_cents"] == 100000
        e2 = collect_premium(policy, 55000)
        assert e2["running_balance_cents"] == 155000

        fresh = get_policy_fresh(policy["id"], FIN)
        assert fresh["collected_cents"] == 155000
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 155000

    def test_ledger_entry_is_append_only_shape(self, api):
        """PRD §2.4: "The TrustLedgerEntry is the deliberate exception. A
        ledger entry is an immutable, append-only record: it carries `id` and
        `created_at` only — both `updated_at` and `version` are absent, and a
        posted entry can never be modified or deleted."

        Design: Corner/entities/trust_ledger_entry_immutable_record
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Ledger Co")
        policy = bind_policy(policy)
        entry = collect_premium(policy, 155000)

        fresh = validate_success(api.get_ledger_entry(entry["id"], FIN))
        assert_ledger_entry(fresh)
        assert fresh["entry_type"] == "COLLECTION"
        assert fresh["amount_cents"] == 155000
        assert fresh["running_balance_cents"] == 155000
        assert fresh["policy_id"] == policy["id"]

    def test_bind_side_effect_visible_immediately_on_program_get(self, api):
        """PRD §2.4: "Consistency is immediate: any derived field affected by
        a mutation — premiums, consumed capacity, trust balances, loss ratios —
        is recomputed within the same request and visible in that request's
        response."

        Design: Corner/consistency_model/immediate_visibility_of_mutation_and_side_effects
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Immed Co")
        bound = validate_success(api.bind_policy(policy["id"], UW))
        assert bound["status"] == "BOUND", "mutation visible in the bind response"

        prog = get_program_fresh(program["id"])
        assert prog["consumed_aggregate_cents"] == 155000, \
            "side effect visible on the very next GET without any recompute call"


class TestRemittances:
    def test_low_tier_two_percent_holdback(self, api):
        """PRD §3.5: "when the net before holdback is at least 100,000 cents
        (one thousand dollars), the holdback is ten percent of it; otherwise
        it is two percent — the holdback itself rounded half-up to whole
        cents. The remittance is the net before holdback minus the holdback."

        Design: Corner/calculations/remittance_low_tier_two_percent
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Low Tier")
        policy = bind_policy(policy)
        collect_premium(policy, 100000)
        # basis 100000; commission 15% = 15000; net 85000 (< 100000) -> 2% = 1700;
        # remittance 83300.
        entry = validate_success(api.record_remittance(
            program["id"], {"declared_amount_cents": 83300}, FIN), expected_status=201)
        assert entry["entry_type"] == "CARRIER_REMITTANCE"
        assert entry["amount_cents"] == -83300
        assert entry["basis_cents"] == 100000
        assert entry["running_balance_cents"] == 16700
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 16700

    def test_holdback_tier_keys_on_net_before_holdback(self, api):
        """PRD §3.5: "Subtracting the commission from the basis yields the net
        before holdback. The holdback tier keys on that net figure, not on the
        final remittance: when the net before holdback is at least 100,000
        cents (one thousand dollars), the holdback is ten percent of it."

        Design: Difficulty/combinatorial_formula/remittance_holdback_tier_evaluation_order
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"commission_rate_pct": 0.20})
        policy = quote_policy(program, insured_name="Remit Co")
        policy = bind_policy(policy)
        collect_premium(policy, 125000)
        # basis 125000; commission 20% = 25000; net 100000 == threshold -> 10%
        # holdback = 10000; remittance = 90000. Keying on the final remittance
        # (90000 < 100000) would wrongly pick the 2% tier (98000).
        entry = validate_success(api.record_remittance(
            program["id"], {"declared_amount_cents": 90000}, FIN), expected_status=201)
        assert entry["amount_cents"] == -90000
        assert entry["basis_cents"] == 125000
        assert entry["running_balance_cents"] == 35000
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 35000

    def test_wrong_tier_selection_would_mismatch(self, api):
        """PRD §3.5: "The holdback tier keys on that net figure, not on the
        final remittance: when the net before holdback is at least 100,000
        cents (one thousand dollars), the holdback is ten percent of it;
        otherwise it is two percent." and "if `declared_amount_cents` differs
        from the computed remittance, the request is rejected with
        `ERR_REMITTANCE_MISMATCH`." — declaring the 2%-tier remittance (98000)
        against a net-before-holdback of exactly 100000 mismatches the
        pinned 10%-tier computation.

        Design: Difficulty/combinatorial_formula/remittance_holdback_tier_evaluation_order
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"commission_rate_pct": 0.20})
        policy = quote_policy(program, insured_name="Tier Probe")
        policy = bind_policy(policy)
        collect_premium(policy, 125000)
        # net before holdback == 100000 -> 10% tier -> computed remittance
        # 90000. A declaration of 98000 (the 2%-tier answer) is a mismatch.
        resp = api.record_remittance(
            program["id"], {"declared_amount_cents": 98000}, FIN)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_MISMATCH)

    def test_remittance_with_zero_basis_rejected(self, api):
        """PRD §3.5: "if the unremitted-collections basis is zero, there is
        `ERR_NOTHING_TO_REMIT`." PRD §3.5: "The fiduciary-safety check comes
        first ... The fiscal checks follow" — so the basis check is reachable
        only once the floor check passes: a first remittance drains the basis
        to zero, and the second request declares an amount that keeps the
        balance at the floor.

        Design: Corner/calculations/remittance_with_zero_basis_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Zero Basis")
        policy = bind_policy(policy)
        collect_premium(policy, 100000)
        # basis 100000; commission 15000; net 85000 -> 2% holdback 1700;
        # remittance 83300. After it posts, basis_cents 100000 is consumed:
        # the unremitted-collections basis is zero, balance is 16700.
        validate_success(api.record_remittance(
            program["id"], {"declared_amount_cents": 83300}, FIN),
            expected_status=201)
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 16700
        # Declaring 6700 lands the balance exactly on the 10000 floor (not
        # below it), so the fiduciary-safety check passes and the zero-basis
        # fiscal check is the one that fires.
        resp = api.record_remittance(
            program["id"], {"declared_amount_cents": 6700}, FIN)
        validate_error(resp, ApiErrorId.ERR_NOTHING_TO_REMIT)
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 16700, "rejected remittance posts nothing"

    def test_remittance_declared_mismatch_rejected(self, api):
        """PRD §3.5: "if `declared_amount_cents` differs from the computed
        remittance, the request is rejected with `ERR_REMITTANCE_MISMATCH`."

        Design: Corner/calculations/remittance_declared_mismatch_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 1000000},
            allocation_overrides={"allocated_cents": 500000},
            guideline_overrides={"max_policy_premium_cents": 500000})
        policy = quote_policy(program, insured_name="Mismatch Co", exposure_units=240,
                              coverage_limit_cents=900000)
        policy = bind_policy(policy)  # gross 365000
        collect_premium(policy, 365000)
        # computed remittance: net 365000 - 54750 = 310250 >= 100000 -> 10%
        # holdback 31025 -> 279225. Declaring 279226 mismatches; the floor is
        # not implicated (365000 - 279226 = 85774 >= 10000).
        resp = api.record_remittance(
            program["id"], {"declared_amount_cents": 279226}, FIN)
        validate_error(resp, ApiErrorId.ERR_REMITTANCE_MISMATCH)
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 365000

    def test_trust_floor_breach_beats_remittance_mismatch(self, api):
        """PRD §3.5: "The fiduciary-safety check comes first: subtracting the
        declared amount from `trust_balance_cents` must not push the balance
        below the program's `min_trust_balance_cents`, failing with
        `ERR_TRUST_FLOOR_BREACH` (HTTP 422). The fiscal checks follow ... if
        `declared_amount_cents` differs from the computed remittance, the
        request is rejected with `ERR_REMITTANCE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_remittance
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 1000000},
            allocation_overrides={"allocated_cents": 500000},
            guideline_overrides={"max_policy_premium_cents": 500000})
        policy = quote_policy(program, insured_name="Floor Co", exposure_units=240,
                              coverage_limit_cents=900000)
        policy = bind_policy(policy)
        collect_premium(policy, 365000)
        # declared 360000 mismatches computed 279225 AND 365000 - 360000 =
        # 5000 < floor 10000: the safety error wins.
        resp = api.record_remittance(
            program["id"], {"declared_amount_cents": 360000}, FIN)
        validate_error(resp, ApiErrorId.ERR_TRUST_FLOOR_BREACH)

        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 365000
        entries = list_ledger(program["id"])
        assert all(e["entry_type"] != "CARRIER_REMITTANCE" for e in entries)

    def test_trust_floor_allows_exact_floor_boundary(self, api):
        """PRD §3.5: "subtracting the declared amount from
        `trust_balance_cents` must not push the balance below the program's
        `min_trust_balance_cents`, failing with `ERR_TRUST_FLOOR_BREACH`" — a
        declared amount that lands the balance exactly on the floor does not
        breach it.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_remittance
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"commission_rate_pct": 0.20,
                               "min_trust_balance_cents": 35000})
        policy = quote_policy(program, insured_name="Exact Floor")
        policy = bind_policy(policy)
        collect_premium(policy, 125000)
        # computed remittance 90000 lands trust exactly on the 35000 floor:
        # accepted (no breach), proving the floor comparison is "below".
        entry = validate_success(api.record_remittance(
            program["id"], {"declared_amount_cents": 90000}, FIN), expected_status=201)
        assert entry["amount_cents"] == -90000
        prog = get_program_fresh(program["id"], FIN)
        assert prog["trust_balance_cents"] == 35000


class TestFinalAudit:
    def test_final_audit_upward_delta_posts_collection_and_adjusts_capacity(self, api):
        """PRD §3.4: "A final premium audit on a policy in `ISSUED` or
        `EXPIRED` status whose `audit_status` is still `NOT_AUDITED` ... takes
        `actual_exposure_units` and `actual_experience_mod`, runs the identical
        premium formula on those actuals, and stores the result as
        `final_premium_cents`. The delta between final and provisional gross is
        then settled: a positive delta posts a `COLLECTION` ledger entry for
        the additional premium ... and both the tranche's `consumed_cents`
        (floored at zero) and the program's `consumed_aggregate_cents` shift by
        the delta."

        Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_audit_upward
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 2000000},
            allocation_overrides={"allocated_cents": 1000000})
        policy = create_issued_policy(program, insured_name="Acme")
        assert policy["gross_premium_cents"] == 155000

        audited = validate_success(api.final_audit_policy(
            policy["id"], {"actual_exposure_units": 120,
                           "actual_experience_mod": 1.20}, UW))
        # final = round_half_up(120*1500*1.20) + 5000 = 221000.
        assert audited["final_premium_cents"] == 221000
        assert audited["gross_premium_cents"] == 155000, "provisional preserved"
        assert audited["audit_status"] == "AUDITED"
        assert audited["status"] == "ISSUED"

        prog = get_program_fresh(program["id"])
        assert prog["consumed_aggregate_cents"] == 221000, "155000 + 66000 delta"
        entries = list_ledger(program["id"])
        latest = entries[-1]
        assert latest["entry_type"] == "COLLECTION"
        assert latest["amount_cents"] == 66000
        assert latest["running_balance_cents"] == 221000

    def test_final_audit_zero_delta_posts_no_ledger_entry(self, api):
        """PRD §3.4: "The delta between final and provisional gross is then
        settled: a positive delta posts a `COLLECTION` ledger entry for the
        additional premium, a negative delta posts a `REFUND` entry carrying
        the negative amount" — with a zero delta neither branch posts.

        Design: Difficulty/dual_variant_calc/premium_provisional_vs_final_audit_upward
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = create_issued_policy(program, insured_name="Exact Co")
        before = len(list_ledger(program["id"]))

        audited = validate_success(api.final_audit_policy(
            policy["id"], {"actual_exposure_units": 100,
                           "actual_experience_mod": 1.0}, UW))
        assert audited["final_premium_cents"] == 155000
        assert audited["audit_status"] == "AUDITED"
        after = list_ledger(program["id"])
        assert len(after) == before, "zero delta posts no ledger entry"


class TestParallelDimensions:
    def test_audit_and_lifecycle_dimensions_are_independent(self, api):
        """PRD §3.4: "A final premium audit on a policy in `ISSUED` or
        `EXPIRED` status whose `audit_status` is still `NOT_AUDITED` — anything
        else is rejected with `ERR_INVALID_STATE`" and "The policy's
        `audit_status` becomes `AUDITED`" — the audit dimension evolves while
        the lifecycle status stays `ISSUED`; a later cancellation request moves
        only the lifecycle (`BOUND`/`ISSUED` → `PENDING_CANCELLATION`).

        Design: Difficulty/non_linear_state_machine/policy_parallel_lifecycle_and_audit_dimensions
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = create_issued_policy(program, insured_name="Par Co")
        assert policy["audit_status"] == "NOT_AUDITED"
        assert policy["status"] == "ISSUED"

        audited = validate_success(api.final_audit_policy(
            policy["id"], {"actual_exposure_units": 100,
                           "actual_experience_mod": 1.0}, UW))
        assert audited["audit_status"] == "AUDITED"
        assert audited["status"] == "ISSUED"

        cancelled = validate_success(api.cancel_policy(
            policy["id"], {"cancellation_date": "2026-12-01T00:00:00Z",
                           "reason": "CARRIER_REQUEST"}, UW))
        assert cancelled["status"] == "PENDING_CANCELLATION"
        assert cancelled["audit_status"] == "AUDITED"
        assert cancelled["pre_cancel_status"] == "ISSUED"

    def test_second_final_audit_rejected(self, api):
        """PRD §3.4: "The policy's `audit_status` becomes `AUDITED`, and a
        policy may be final-audited only once" — a second audit fails the
        `audit_status` still `NOT_AUDITED` precondition ("anything else is
        rejected with `ERR_INVALID_STATE`").

        Design: Difficulty/non_linear_state_machine/policy_parallel_lifecycle_and_audit_dimensions
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = create_issued_policy(program, insured_name="Once Co")
        validate_success(api.final_audit_policy(
            policy["id"], {"actual_exposure_units": 100,
                           "actual_experience_mod": 1.0}, UW))
        resp = api.final_audit_policy(
            policy["id"], {"actual_exposure_units": 110,
                           "actual_experience_mod": 1.0}, UW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = get_policy_fresh(policy["id"])
        assert fresh["audit_status"] == "AUDITED"
        assert fresh["final_premium_cents"] == 155000
