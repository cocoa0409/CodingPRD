"""Program lifecycle: activation gates, OCC on superseding creates, guideline
supersede semantics, carrier/TPA suspension gates, terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_allocation,
    assert_guideline,
    create_allocation,
    create_allocation_payload,
    create_carrier,
    create_filing,
    create_guideline,
    create_guideline_payload,
    create_program,
    create_tpa,
    get_program_fresh,
    make_carrier_underwriter_headers,
    setup_active_program,
    setup_prepared_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
AUD = TEST_USERS["carrier_auditor_headers"]


class TestActivationGates:
    def test_suspended_carrier_blocks_activation_then_unblocks(self, api):
        """PRD §3.2: "Activation moves the program `PROPOSED → ACTIVE` and is
        permitted only when the carrier itself is `ACTIVE` (a `SUSPENDED`
        carrier's activation attempt fails with `ERR_INVALID_STATE`)."
        PRD §3.1: "The carrier-suspension action toggles: invoking it on an
        `ACTIVE` carrier moves it to `SUSPENDED`, and invoking it on a
        `SUSPENDED` carrier restores it to `ACTIVE`."

        Design: Corner/entities/suspended_carrier_blocks_program_activation
        """
        carrier, program, _g, _a, _f = setup_prepared_program()
        cu = make_carrier_underwriter_headers(carrier["id"])

        get_success = validate_success(api.suspend_carrier(carrier["id"], ADMIN))
        assert get_success["status"] == "SUSPENDED"

        blocked = api.activate_program(program["id"], cu)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)

        restored = validate_success(api.suspend_carrier(carrier["id"], ADMIN))
        assert restored["status"] == "ACTIVE"

        ok = validate_success(api.activate_program(program["id"], cu))
        assert ok["status"] == "ACTIVE"

    def test_program_activate_twice_rejected(self, api):
        """PRD §2.11: "An entity in a terminal state rejects every further
        transition with `ERR_INVALID_STATE` (HTTP 409)." — and a state-legality
        violation generally: activation is defined only from `PROPOSED`
        (PRD §3.2: "Activation moves the program `PROPOSED → ACTIVE`").

        Design: Corner/state_machines/program_activate_twice_rejected
        """
        carrier, program, _g, _a, _f = setup_active_program()
        v_after = program["version"]
        cu = make_carrier_underwriter_headers(carrier["id"])

        resp = api.activate_program(program["id"], cu)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        fresh = get_program_fresh(program["id"])
        assert fresh["version"] == v_after, "failed activate must not bump version"

    def test_terminal_program_rejects_child_creation(self, api):
        """PRD §3.8: "`TERMINATED` and `DECLINED` are terminal; a terminal
        program rejects any child creation or further transition with
        `ERR_PROGRAM_TERMINAL`."

        Design: Corner/state_machines/program_terminal_lockdown_rejects_child_creation
        """
        carrier, program, _g, _a, _f = setup_active_program()
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.enter_runoff_program(program["id"], cu))
        term = validate_success(api.terminate_program(
            program["id"], {"termination_reason": "wind-down"}, cu))
        assert term["status"] == "TERMINATED"

        resp = api.create_policy(program["id"], {
            "insured_name": "Too Late", "state_code": "CA", "class_code": "ARTISAN",
            "exposure_units": 10, "coverage_limit_cents": 100000,
            "experience_mod": 1.0,
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2027-08-01T00:00:00Z"}, UW)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_TERMINAL)


class TestGuidelineSupersede:
    def test_new_scope_does_not_supersede_other_scope(self, api):
        """PRD §3.2: "At most one guideline per scope may be `ACTIVE`: creating
        a guideline for an already-occupied scope atomically moves the prior
        `ACTIVE` guideline of that scope to `SUPERSEDED` as part of the same
        create."

        Design: Corner/entities/guideline_new_scope_does_not_supersede_other_scope
        """
        carrier = create_carrier()
        program = create_program(carrier)
        g1 = create_guideline(program, class_code="ARTISAN")
        g2 = create_guideline(program, class_code="TRUCKING",
                              max_policy_premium_cents=400000,
                              max_policy_limit_cents=2000000,
                              min_policy_premium_cents=8000)
        assert_guideline(g1)
        assert_guideline(g2)
        g1_fresh = validate_success(api.get_guideline(g1["id"], UW))
        assert g1_fresh["status"] == "ACTIVE"
        assert g2["status"] == "ACTIVE"

    def test_active_cardinality_conserved_under_supersedes(self, api):
        """PRD §3.2: "At most one guideline per scope may be `ACTIVE`: creating
        a guideline for an already-occupied scope atomically moves the prior
        `ACTIVE` guideline of that scope to `SUPERSEDED` as part of the same
        create."

        Design: Difficulty/compensating_invariant/active_guideline_cardinality_conserved_under_supersede
        """
        carrier = create_carrier()
        program = create_program(carrier)
        g1 = create_guideline(program, max_policy_premium_cents=250000)
        g2 = create_guideline(program, max_policy_premium_cents=200000)
        g3 = create_guideline(program, max_policy_premium_cents=300000,
                              min_policy_premium_cents=4000)

        assert validate_success(api.get_guideline(g1["id"], UW))["status"] == "SUPERSEDED"
        assert validate_success(api.get_guideline(g2["id"], UW))["status"] == "SUPERSEDED"
        assert g3["status"] == "ACTIVE"

        lst = api.list_program_guidelines(program["id"], UW, params={"status": "ACTIVE"})
        rows, meta = validate_paginated(lst)
        assert meta["total_count"] == 1
        assert rows[0]["id"] == g3["id"]

    def test_program_version_increments_once_per_guideline_create(self, api):
        """PRD §2.10: "the program itself gains a `version` increment on each
        of its own lifecycle transitions and on each guideline or
        capacity-allocation create."

        Design: Difficulty/compensating_invariant/active_guideline_cardinality_conserved_under_supersede
        """
        carrier = create_carrier()
        program = create_program(carrier)
        v0 = program["version"]
        create_guideline(program)
        v1 = get_program_fresh(program["id"])["version"]
        create_guideline(program)
        v2 = get_program_fresh(program["id"])["version"]
        assert v1 == v0 + 1
        assert v2 == v0 + 2


class TestOptimisticConcurrency:
    def test_guideline_create_stale_version_rejected(self, api):
        """PRD §2.9: "If `expected_program_version` does not equal the
        program's current `version`, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and nothing is superseded."

        Design: Corner/cross_cutting_layers/occ_guideline_create_stale_version_rejected
        """
        carrier = create_carrier()
        program = create_program(carrier)
        v1 = program["version"]
        g1 = create_guideline(program, class_code="ARTISAN")  # program now v1+1

        stale = api.create_guideline(
            program["id"],
            create_guideline_payload(v1, class_code="TRUCKING",
                                     max_policy_premium_cents=400000),
            UW)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        # G1 of a different scope is untouched by the rejected create.
        assert validate_success(api.get_guideline(g1["id"], UW))["status"] == "ACTIVE"

        v_now = get_program_fresh(program["id"])["version"]
        ok = api.create_guideline(
            program["id"],
            create_guideline_payload(v_now, class_code="TRUCKING",
                                     max_policy_premium_cents=400000),
            UW)
        validate_success(ok, expected_status=201)
        assert get_program_fresh(program["id"])["version"] == v1 + 2

    def test_capacity_create_stale_version_rejected_then_fresh_supersedes(self, api):
        """PRD §2.9: "creating an underwriting guideline, and creating a
        capacity allocation ... must carry `expected_program_version` ... If
        `expected_program_version` does not equal the program's current
        `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.2: "Creating a tranche supersedes the program's current
        non-terminal tranche — `ACTIVE` or `EXHAUSTED` becomes `SUPERSEDED`."

        Design: Corner/cross_cutting_layers/occ_capacity_create_stale_version_rejected
        """
        carrier = create_carrier()
        program = create_program(carrier)
        cu = make_carrier_underwriter_headers(carrier["id"])
        v1 = program["version"]
        a1 = create_allocation(program, allocated_cents=300000)

        stale = api.create_capacity_allocation(
            program["id"],
            create_allocation_payload(v1, period_label="2026-Q4",
                                      allocated_cents=400000),
            cu)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        rows, meta = validate_paginated(
            api.list_program_allocations(program["id"], cu))
        assert meta["total_count"] == 1, "stale create must not persist a tranche"

        v_now = get_program_fresh(program["id"], cu)["version"]
        a2 = validate_success(api.create_capacity_allocation(
            program["id"],
            create_allocation_payload(v_now, period_label="2026-Q4",
                                      allocated_cents=400000),
            cu), expected_status=201)
        assert_allocation(a2)
        assert a2["status"] == "ACTIVE"
        a1_fresh = validate_success(api.get_allocation(a1["id"], cu))
        assert a1_fresh["status"] == "SUPERSEDED"


class TestSuspensionGates:
    def test_suspended_tpa_blocks_new_appointment(self, api):
        """PRD §3.6: "the TPA must be `ACTIVE` already, or the create fails
        with `ERR_TPA_SUSPENDED`." PRD §3.1: "only the creation of new
        appointments for that TPA and the activation of pending ones are
        blocked, surfacing as `ERR_TPA_SUSPENDED`."

        Design: Corner/entities/suspended_tpa_blocks_new_appointment
        """
        carrier = create_carrier()
        program = create_program(carrier)
        tpa = create_tpa()
        validate_success(api.suspend_tpa(tpa["id"], ADMIN))

        cu = make_carrier_underwriter_headers(carrier["id"])
        resp = api.create_appointment(program["id"], {
            "tpa_id": tpa["id"], "claim_type": "LIABILITY",
            "authority_limit_cents": 100000,
            "effective_from": "2026-08-01T00:00:00Z",
            "effective_to": "2027-08-01T00:00:00Z"}, cu)
        validate_error(resp, ApiErrorId.ERR_TPA_SUSPENDED)
