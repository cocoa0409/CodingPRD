"""Policy quoting gauntlet, provisional premium computation, binding capacity
boundaries, issue collection gate, and policy listing pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bind_policy,
    collect_premium,
    create_guideline,
    create_policy_payload,
    get_policy_fresh,
    get_program_fresh,
    make_carrier_underwriter_headers,
    quote_policy,
    set_clock,
    setup_active_program,
    setup_prepared_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]


class TestPremiumComputation:
    def test_mod_clamped_before_multiply_then_fee_added(self, api):
        """PRD §3.4: "The experience modification factor is clamped before it
        multiplies anything: an `experience_mod` below 0.75 is treated as 0.75,
        and one above 1.25 as 1.25. The raw premium is the exposure units
        multiplied by the base rate multiplied by the clamped factor, rounded
        half-up to whole cents. The flat `policy_fee_cents` is then added."
        PRD §3.4: "The MGA's compensation, `mga_commission_cents`, is the gross
        premium multiplied by the program's `commission_rate_pct`, rounded
        half-up to whole cents."

        Design: Difficulty/combinatorial_formula/premium_clamp_multiply_fee_interaction
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Clamp Co",
                              exposure_units=100, experience_mod=1.30)
        # 100 * 1500 * 1.25 (clamped from 1.30) + 5000 = 192500, not 200000.
        assert policy["gross_premium_cents"] == 192500
        assert policy["mga_commission_cents"] == 28875  # round_half_up(192500*0.15)
        assert policy["status"] == "QUOTED"

    def test_mod_clamped_at_low_end(self, api):
        """PRD §3.4: "an `experience_mod` below 0.75 is treated as 0.75" — the
        clamp bounds both ends of the factor range before multiplication.

        Design: Difficulty/combinatorial_formula/premium_clamp_multiply_fee_interaction
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="LowMod Co",
                              exposure_units=100, experience_mod=0.50)
        # 100 * 1500 * 0.75 + 5000 = 117500.
        assert policy["gross_premium_cents"] == 117500
        assert policy["mga_commission_cents"] == 17625

    def test_minimum_premium_floor_applied(self, api):
        """PRD §3.4: "The flat `policy_fee_cents` is then added, and
        `gross_premium_cents` is the greater of that sum and the guideline's
        `min_policy_premium_cents`."
        PRD §3.2: "an optional `min_policy_premium_cents` floor that defaults
        to zero and is applied by the rating calculation."

        Design: Corner/calculations/premium_minimum_floor_applied
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            guideline_overrides={"min_policy_premium_cents": 10000})
        policy = quote_policy(program, insured_name="Floor Co", exposure_units=1)
        # 1 * 1500 * 1.0 + 5000 = 6500 -> floored to 10000.
        assert policy["gross_premium_cents"] == 10000
        # Commission is computed on the floored gross: round_half_up(10000*0.15).
        assert policy["mga_commission_cents"] == 1500


class TestQuoteGauntlet:
    def test_gross_above_guideline_premium_cap_rejected(self, api):
        """PRD §3.4: "The premium ceiling is enforced after this calculation
        at quote time and re-checked at bind time: a gross above the
        guideline's `max_policy_premium_cents` is rejected with
        `ERR_GUIDELINE_PREMIUM_LIMIT`."

        Design: Corner/calculations/premium_above_guideline_max_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        # 200 * 1500 * 1.25 (clamped from 1.30) + 5000 = 380000 > cap 250000.
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="Too Big", exposure_units=200, experience_mod=1.30), UW)
        validate_error(resp, ApiErrorId.ERR_GUIDELINE_PREMIUM_LIMIT)

    def test_coverage_limit_above_guideline_rejected(self, api):
        """PRD §3.4: "`coverage_limit_cents` must not exceed the guideline's
        `max_policy_limit_cents` (`ERR_GUIDELINE_LIMIT_EXCEEDED`)"."

        Design: Corner/calculations/coverage_limit_above_guideline_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="Overlimit", coverage_limit_cents=1500000), UW)
        validate_error(resp, ApiErrorId.ERR_GUIDELINE_LIMIT_EXCEEDED)

    def test_state_not_covered_rejected(self, api):
        """PRD §3.4: "the `state_code` must appear in the program's
        `states_covered` (`ERR_STATE_NOT_COVERED`)."

        Design: Corner/validations/quote_state_not_covered_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="NY Co", state_code="NY"), UW)
        validate_error(resp, ApiErrorId.ERR_STATE_NOT_COVERED)

    def test_class_without_guideline_rejected(self, api):
        """PRD §3.4: "an `ACTIVE` guideline must exist for the state-and-class
        scope (`ERR_CLASS_NOT_ELIGIBLE`)."

        Design: Corner/validations/quote_class_without_guideline_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="Class Co", class_code="TRUCKING"), UW)
        validate_error(resp, ApiErrorId.ERR_CLASS_NOT_ELIGIBLE)

    def test_class_not_in_filing_rates_rejected(self, api):
        """PRD §3.4: "an `EFFECTIVE` filing must exist for the program and
        state (`ERR_NO_EFFECTIVE_FILING`) and must carry the class in its
        `base_rates` (`ERR_CLASS_NOT_FILED`)."

        Design: Corner/validations/quote_class_not_in_filing_rates_rejected
        """
        # Guideline exists for CA/HAULER but the EFFECTIVE filing rates only ARTISAN.
        carrier, program, _g, _a, _f = setup_active_program()
        create_guideline(program, class_code="HAULER",
                         max_policy_premium_cents=300000,
                         min_policy_premium_cents=6000)
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="Haul Co", class_code="HAULER"), UW)
        validate_error(resp, ApiErrorId.ERR_CLASS_NOT_FILED)

    def test_state_with_no_effective_filing_rejected(self, api):
        """PRD §3.4: "an `EFFECTIVE` filing must exist for the program and
        state (`ERR_NO_EFFECTIVE_FILING`)."

        Design: Corner/validations/quote_state_with_no_effective_filing_rejected
        """
        carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"states_covered": ["CA", "NV"]})
        create_guideline(program, state_code="NV")
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="NV Co", state_code="NV"), UW)
        validate_error(resp, ApiErrorId.ERR_NO_EFFECTIVE_FILING)

    def test_temporal_window_check_beats_business_constraint(self, api):
        """PRD §3.4: "Quoting runs a gauntlet in the platform's fixed order
        (§2.11): state legality first ...; then the temporal check — the
        policy window must sit inside the half-open window of an `EFFECTIVE`
        filing for the program and state, and `effective_from` may not precede
        the clock, failing as `ERR_POLICY_WINDOW_OUTSIDE_FILING`; then business
        constraints — ... an `ACTIVE` guideline must exist for the
        state-and-class scope (`ERR_CLASS_NOT_ELIGIBLE`) ..."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_quote
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        # effective_from 2027-08-05 is outside the filing window ending
        # 2027-08-01 (temporal) AND class TRUCKING has no guideline
        # (constraint): the temporal error wins.
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="Dual Fail", class_code="TRUCKING",
            effective_from="2027-08-05T00:00:00Z",
            effective_to="2028-08-01T00:00:00Z"), UW)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_OUTSIDE_FILING)

        rows, meta = validate_paginated(
            api.list_program_policies(program["id"], UW))
        assert meta["total_count"] == 0

    def test_temporal_window_check_on_stale_effective_from(self, api):
        """PRD §3.4: "the policy window must sit inside the half-open window
        of an `EFFECTIVE` filing for the program and state, and
        `effective_from` may not precede the clock, failing as
        `ERR_POLICY_WINDOW_OUTSIDE_FILING`."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_quote
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        set_clock("2026-09-01T00:00:00Z")
        # effective_from 2026-08-15 precedes the clock (2026-09-01): temporal
        # violation even though class ARTISAN has a guideline.
        resp = api.create_policy(program["id"], create_policy_payload(
            insured_name="Past Co",
            effective_from="2026-08-15T00:00:00Z",
            effective_to="2027-08-01T00:00:00Z"), UW)
        validate_error(resp, ApiErrorId.ERR_POLICY_WINDOW_OUTSIDE_FILING)


class TestBinding:
    def test_bind_on_runoff_program_reports_state_before_fiscal(self, api):
        """PRD §3.4: "The checks run in order: the program must be `ACTIVE`
        (`ERR_PROGRAM_NOT_ACTIVE`); ... then the fiscal checks — ... the
        tranche's available capacity ... must cover the gross premium
        (`ERR_TRANCHE_EXHAUSTED`)."
        PRD §3.8: "Entering run-off ... stops new business — new policy quotes
        and binds are rejected with `ERR_PROGRAM_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bind
        """
        carrier, program, _g, _a, _f = setup_active_program(
            allocation_overrides={"allocated_cents": 100000})
        policy = quote_policy(program, insured_name="Prio Co")  # gross 155000
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))

        resp = api.bind_policy(policy["id"], UW)
        # Both violations hold (RUN_OFF state; tranche 100000 < 155000); the
        # state error is returned.
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        assert get_policy_fresh(policy["id"])["status"] == "QUOTED"

    def test_runoff_program_bind_reports_state_even_with_ample_tranche(self, api):
        """PRD §3.4: "The checks run in order: the program must be `ACTIVE`
        (`ERR_PROGRAM_NOT_ACTIVE`); ... then the fiscal checks — ... the
        tranche's available capacity (its `allocated_cents` minus its
        `consumed_cents`) must cover the gross premium (`ERR_TRANCHE_EXHAUSTED`)."
        — with ample tranche headroom the fiscal gate does not hold at all,
        isolating the state gate as the sole cause.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bind
        """
        carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Ample Co")  # gross 155000
        cu = make_carrier_underwriter_headers(carrier["id"])
        # Run-off withdraws nothing; the QUOTED policy stays bindable-shaped.
        validate_success(api.enter_runoff_program(program["id"], cu))
        resp = api.bind_policy(policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        assert get_policy_fresh(policy["id"])["status"] == "QUOTED"
        prog = get_program_fresh(program["id"])
        assert prog["consumed_aggregate_cents"] == 0

    def test_bind_blocked_after_runoff_while_active_bind_succeeded(self, api):
        """PRD §3.8: "Entering run-off (from `ACTIVE` or `SUSPENDED` into
        `RUN_OFF`) stops new business — new policy quotes and binds are
        rejected with `ERR_PROGRAM_NOT_ACTIVE` — while in-force policies
        simply continue to expiry."

        Design: Difficulty/cross_entity_state_dependency/policy_bind_requires_program_active
        """
        carrier, program, _g, _a, _f = setup_active_program()
        pol_a = quote_policy(program, insured_name="A")
        pol_b = quote_policy(program, insured_name="B")

        bound = bind_policy(pol_a)
        assert bound["status"] == "BOUND"

        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))
        resp = api.bind_policy(pol_b["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)

        prog = get_program_fresh(program["id"])
        assert prog["consumed_aggregate_cents"] == 155000, \
            "only the pre-runoff bind consumed capacity"

    def test_bind_succeeds_while_program_active(self, api):
        """PRD §3.4: "Binding moves `QUOTED → BOUND` and is where capacity is
        consumed. The checks run in order: the program must be `ACTIVE`
        (`ERR_PROGRAM_NOT_ACTIVE`) ..." — with the program ACTIVE and ample
        capacity, the same bind succeeds, isolating the program-state
        precondition as the deciding factor.

        Design: Difficulty/cross_entity_state_dependency/policy_bind_requires_program_active
        """
        carrier, program, _g, allocation, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Isolation Co")
        bound = validate_success(api.bind_policy(policy["id"], UW))
        assert bound["status"] == "BOUND"
        assert bound["bound_at"] is not None
        prog = get_program_fresh(program["id"])
        assert prog["consumed_aggregate_cents"] == bound["gross_premium_cents"]
        tranche = validate_success(api.get_allocation(allocation["id"], UW))
        assert tranche["consumed_cents"] == bound["gross_premium_cents"]

    def test_bind_from_bound_invalid_state_no_double_consumption(self, api):
        """PRD §3.4: "Binding moves `QUOTED → BOUND`" — a repeat bind is a
        state-legality violation (`ERR_INVALID_STATE`, PRD §2.11) and must not
        consume capacity twice: "`consumed_aggregate_cents` accumulates the
        gross written premium of every policy in `BOUND`, `ISSUED`, or
        `PENDING_CANCELLATION`" (PRD §2.7).

        Design: Corner/state_machines/policy_bind_from_bound_invalid_state
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Double Bind")
        bind_policy(policy)

        resp = api.bind_policy(policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        prog = get_program_fresh(program["id"])
        assert prog["consumed_aggregate_cents"] == 155000

    def test_bind_after_quote_valid_until_rejected_boundary(self, api):
        """PRD §3.4: "The quote remains bindable for thirty days:
        `quote_valid_until` is set to the creation clock plus 30 days."
        PRD §3.4: "the clock must be no later than `quote_valid_until`
        (`ERR_QUOTE_EXPIRED`)."

        Design: Corner/state_machines/bind_after_quote_valid_until_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        pol_ok = quote_policy(program, insured_name="OnTime", exposure_units=10,
                              coverage_limit_cents=100000)
        pol_late = quote_policy(program, insured_name="TooLate", exposure_units=10,
                                coverage_limit_cents=100000)
        # Created at the startup clock 2026-08-01 -> quote_valid_until 2026-08-31.
        assert pol_ok["quote_valid_until"].startswith("2026-08-31")

        set_clock("2026-08-31T00:00:00Z")
        bound = bind_policy(pol_ok)
        assert bound["status"] == "BOUND", "bind at exactly quote_valid_until is allowed"

        set_clock("2026-09-01T00:00:00Z")
        resp = api.bind_policy(pol_late["id"], UW)
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
        assert get_policy_fresh(pol_late["id"])["status"] == "QUOTED"


class TestCapacityBoundaries:
    def test_tranche_exact_fit_flips_exhausted_then_over_rejected(self, api):
        """PRD §2.7: "When consumption reaches the allocation exactly, the
        tranche flips to `EXHAUSTED`: it still occupies the program's
        single-allocation slot but accepts no further consumption."
        PRD §3.4: "the tranche's available capacity (its `allocated_cents`
        minus its `consumed_cents`) must cover the gross premium
        (`ERR_TRANCHE_EXHAUSTED`)."

        Design: Difficulty/boundary_precision_check/tranche_exact_fit_then_one_cent_over
        """
        _carrier, program, _g, allocation, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 500000},
            allocation_overrides={"allocated_cents": 295000})
        p1 = quote_policy(program, insured_name="P1")                     # 155000
        p2 = quote_policy(program, insured_name="P2", exposure_units=90)  # 140000
        p3 = quote_policy(program, insured_name="P3", exposure_units=1,
                          coverage_limit_cents=50000)                     # 6500
        bind_policy(p1)
        bound2 = bind_policy(p2)
        assert bound2["status"] == "BOUND", "exact fit (295000 == 295000) is allowed"

        tranche = validate_success(api.get_allocation(allocation["id"], UW))
        assert tranche["status"] == "EXHAUSTED"
        assert tranche["consumed_cents"] == 295000

        resp = api.bind_policy(p3["id"], UW)
        validate_error(resp, ApiErrorId.ERR_TRANCHE_EXHAUSTED)
        assert get_policy_fresh(p3["id"])["status"] == "QUOTED"

    def test_exhausted_tranche_occupies_slot_but_accepts_no_consumption(self, api):
        """PRD §2.7: "When consumption reaches the allocation exactly, the
        tranche flips to `EXHAUSTED`: it still occupies the program's
        single-allocation slot but accepts no further consumption."

        Design: Difficulty/boundary_precision_check/tranche_exact_fit_then_one_cent_over
        """
        _carrier, program, _g, allocation, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 500000},
            allocation_overrides={"allocated_cents": 155000})
        p1 = quote_policy(program, insured_name="Only")  # exact fit
        bind_policy(p1)
        tranche = validate_success(api.get_allocation(allocation["id"], UW))
        assert tranche["status"] == "EXHAUSTED"

        p2 = quote_policy(program, insured_name="Next", exposure_units=10,
                          coverage_limit_cents=100000)  # gross 20000
        resp = api.bind_policy(p2["id"], UW)
        validate_error(resp, ApiErrorId.ERR_TRANCHE_EXHAUSTED)

    def test_program_aggregate_exact_fit_then_over(self, api):
        """PRD §3.4: "the program's aggregate headroom (`aggregate_limit_cents`
        minus `consumed_aggregate_cents`) must cover it as well
        (`ERR_CAPACITY_EXCEEDED`)."

        Design: Corner/validations/program_aggregate_exact_fit_then_over
        """
        _carrier, program, _g, _a, _f = setup_active_program(
            program_overrides={"aggregate_limit_cents": 295000},
            allocation_overrides={"allocated_cents": 500000})
        p1 = quote_policy(program, insured_name="A1")                     # 155000
        p2 = quote_policy(program, insured_name="A2", exposure_units=90)  # 140000
        p3 = quote_policy(program, insured_name="A3", exposure_units=1,
                          coverage_limit_cents=50000)                     # 6500
        bind_policy(p1)
        bound2 = bind_policy(p2)
        assert bound2["status"] == "BOUND", "exact aggregate fit is allowed"

        resp = api.bind_policy(p3["id"], UW)
        # Tranche still has headroom; the program aggregate is the failing gate.
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        assert get_policy_fresh(p3["id"])["status"] == "QUOTED"

    def test_bind_without_any_allocation_rejected(self, api):
        """PRD §3.4: "a non-terminal tranche must exist for the program
        (`ERR_NO_ACTIVE_ALLOCATION`)."

        Design: Corner/validations/bind_without_any_allocation_rejected
        """
        carrier, program, _g, allocation, _f = setup_active_program()
        policy = quote_policy(program, insured_name="No Alloc")
        cu = make_carrier_underwriter_headers(carrier["id"])
        rel = validate_success(api.release_allocation(allocation["id"], cu))
        assert rel["status"] == "RELEASED"

        resp = api.bind_policy(policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ALLOCATION)
        assert get_policy_fresh(policy["id"])["status"] == "QUOTED"


class TestIssuanceGate:
    def test_issue_requires_full_collection_and_collections_accumulate(self, api):
        """PRD §3.4: "Issuance (`BOUND → ISSUED`) is the evidence that money
        preceded paper: it requires `collected_cents` to be at least
        `gross_premium_cents`, failing with `ERR_PREMIUM_NOT_COLLECTED`
        otherwise."

        Design: Corner/validations/issue_without_full_collection_rejected
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        policy = quote_policy(program, insured_name="Part Pay")
        policy = bind_policy(policy)
        collect_premium(policy, 100000)

        resp = api.issue_policy(policy["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PREMIUM_NOT_COLLECTED)

        collect_premium(policy, 55000)
        issued = validate_success(api.issue_policy(policy["id"], UW))
        assert issued["status"] == "ISSUED"
        assert issued["collected_cents"] == 155000


class TestPolicyPagination:
    def test_list_policies_limit_offset_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted, with a minimum accepted
        value of 1 and a maximum of 100. The `offset` parameter sets the
        number of items to skip and defaults to 0." and "Paginated list
        responses carry `limit`, `offset`, `total_count`, and `has_more` in
        the `meta` object of the envelope."

        Design: Corner/entities/policy_list_pagination_limit_offset
        """
        _carrier, program, _g, _a, _f = setup_active_program()
        for name in ("P1", "P2", "P3"):
            quote_policy(program, insured_name=name, exposure_units=10,
                         coverage_limit_cents=100000)

        rows1, meta1 = validate_paginated(api.list_program_policies(
            program["id"], UW, params={"limit": 2, "offset": 0}))
        assert len(rows1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        rows2, meta2 = validate_paginated(api.list_program_policies(
            program["id"], UW, params={"limit": 2, "offset": 2}))
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
