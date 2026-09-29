"""Expiry and reversion close-out: the condition weight table, the deficiency,
the deposit-capped holdback, the segregation-of-duties bar, the three deposit
buckets that must always sum to the deposit, and the estoppel certificate that
an open arbitration blocks."""

from test_helpers import (
    ERR_AMOUNT_NOT_RECONCILED,
    ERR_CROSS_ENTITY_BLOCKED,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    assert_deposit_conserved,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_asset_manager_headers,
    make_lessor_admin_headers,
    make_mortgagee_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PAST_EXPIRATION = "2026-07-01T00:00:00Z"
SCORES = {"structural": 60, "envelope": 70, "systems": 50}


def _assessment_for(api, lease_id):
    rows, meta = validate_paginated(
        api.list_reversion_assessments(
            make_asset_manager_headers("am-1"), {"lease_id": lease_id}
        )
    )
    assert meta["total_count"] == 1, rows
    return rows[0]


def _two_expired_leases_on_different_standards(api):
    """Lease E on SHELL_CONDITION with improvements 60000000 and a 1000000 deposit;
    lease F on FULLY_FITTED with improvements 10000000 and a 5000000 deposit. Both
    expired by one sweep at the default clock, then inspected by am-1 at 60/70/50."""
    lessee = fx.create_lessee(api)
    lease_e = fx.create_lease(
        api, lessee["id"], "PIER-45-E",
        expiration_date=PAST_EXPIRATION, security_deposit_cents=1000000,
    )
    lease_f = fx.create_lease(
        api, lessee["id"], "PIER-45-F",
        expiration_date=PAST_EXPIRATION, improvements_value_cents=10000000,
        reversion_standard_code="FULLY_FITTED",
    )
    report = fx.run_sweep(api)
    world = {"report": report, "lease_e": lease_e, "lease_f": lease_f}
    for label, lease in (("assess_e", lease_e), ("assess_f", lease_f)):
        assessment = _assessment_for(api, lease["id"])
        world[label] = validate_success(
            api.record_inspection(
                assessment["id"],
                f.inspection_payload(SCORES["structural"], SCORES["envelope"],
                                     SCORES["systems"]),
                make_asset_manager_headers("am-1"),
            )
        )
    return world


def test_the_weight_table_is_selected_by_the_snapshotted_condition_standard(api):
    """PRD §3.9: "`weighted_score_bps` is then computed component by component: multiply each component score by its weight in basis points, divide by 100, round half up to a whole basis point, and add the three rounded component figures together — the per-component rounding precedes the addition."

    Design: Difficulty/combinatorial_formula/reversion_holdback_weight_table_then_deficiency_then_deposit_cap
    """
    world = _two_expired_leases_on_different_standards(api)
    assert world["report"]["leases_expired"] == 2
    assert_fields(fx.read_lease(api, world["lease_e"]["id"]),
                  lease_status="EXPIRED", rent_status="FROZEN")

    # 60/70/50 against 6000/3000/1000 gives 3600 + 2100 + 500.
    assert_fields(
        world["assess_e"],
        status="INSPECTED",
        required_standard_code="SHELL_CONDITION",
        weighted_score_bps=6200,
        deficiency_bps=3800,
        inspected_by_user_id="am-1",
    )
    # The same three scores against 4000/3000/3000 give 2400 + 2100 + 1500.
    assert_fields(
        world["assess_f"],
        status="INSPECTED",
        required_standard_code="FULLY_FITTED",
        weighted_score_bps=6000,
        deficiency_bps=4000,
        inspected_by_user_id="am-1",
    )


def test_the_holdback_is_capped_by_the_deposit_actually_held(api):
    """PRD §3.9: "The holdback itself is computed as whichever is smaller of the lease's `deposit_held_cents` and the deficiency-weighted improvements value — the lease's `improvements_value_cents` multiplied by `deficiency_bps`, divided by 10,000 and rounded half up to whole cents — and the supplied `acknowledged_holdback_cents` must equal that computed figure **exactly**, with any discrepancy refused as `ERR_AMOUNT_NOT_RECONCILED`."

    Design: Difficulty/combinatorial_formula/reversion_holdback_weight_table_then_deficiency_then_deposit_cap
    """
    world = _two_expired_leases_on_different_standards(api)

    # 60000000 x 3800 bps is 22800000, far beyond the 1000000 deposit.
    validate_error(
        api.apply_holdback(world["assess_e"]["id"], f.holdback_payload(22800000),
                           make_asset_manager_headers("am-2")),
        ERR_AMOUNT_NOT_RECONCILED,
        expected_status=422,
    )
    applied = validate_success(
        api.apply_holdback(world["assess_e"]["id"], f.holdback_payload(1000000),
                           make_asset_manager_headers("am-2"))
    )
    assert_fields(applied, status="HOLDBACK_APPLIED", holdback_cents=1000000)

    lease = fx.read_lease(api, world["lease_e"]["id"])
    assert_fields(lease, deposit_held_cents=0, deposit_applied_cents=1000000,
                  deposit_refunded_cents=0)
    assert_deposit_conserved(lease)


def test_an_uncapped_holdback_takes_the_deficiency_weighted_improvements_value(api):
    """PRD §3.9: "Application writes `holdback_cents`, adds it to the lease's `deposit_applied_cents`, subtracts it from the lease's `deposit_held_cents` so that held plus applied plus refunded still equals `security_deposit_cents`, increments the lease `version` by one, and moves the assessment `INSPECTED → HOLDBACK_APPLIED`."

    Design: Difficulty/combinatorial_formula/reversion_holdback_weight_table_then_deficiency_then_deposit_cap
    """
    world = _two_expired_leases_on_different_standards(api)
    before = fx.read_lease(api, world["lease_f"]["id"])
    assert_fields(before, deposit_held_cents=5000000, deposit_applied_cents=0)

    # 10000000 x 4000 bps is 4000000, which the 5000000 deposit still covers.
    applied = validate_success(
        api.apply_holdback(world["assess_f"]["id"], f.holdback_payload(4000000),
                           make_asset_manager_headers("am-2"))
    )
    assert_fields(applied, status="HOLDBACK_APPLIED", holdback_cents=4000000)

    lease = fx.read_lease(api, world["lease_f"]["id"])
    assert_fields(lease, deposit_held_cents=1000000, deposit_applied_cents=4000000,
                  deposit_refunded_cents=0, lease_status="EXPIRED")
    assert lease["version"] == before["version"] + 1
    assert_deposit_conserved(lease)


def _inspected_reversion_short_of_the_standard(api):
    """One SHELL_CONDITION lease with improvements 10000000 and the canonical
    5000000 deposit, expired by the sweep and inspected by am-1 at 70/60/50."""
    env = fx.standard_lease(
        api, "PIER-65",
        expiration_date="2026-09-01T00:00:00Z", improvements_value_cents=10000000,
    )
    _report, opened = fx.expire_lease_via_sweep(api, env["lease_id"],
                                                "2026-09-02T00:00:00Z")
    assert opened["status"] == "PENDING_INSPECTION"
    assessment = validate_success(
        api.record_inspection(opened["id"], f.inspection_payload(70, 60, 50),
                              make_asset_manager_headers("am-1"))
    )
    # 70/60/50 against 6000/3000/1000 gives 4200 + 1800 + 500, short of the 7000 pass.
    assert_fields(
        assessment,
        status="INSPECTED",
        required_standard_code="SHELL_CONDITION",
        weighted_score_bps=6500,
        deficiency_bps=3500,
        inspected_by_user_id="am-1",
    )
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, lease_status="EXPIRED", rent_status="FROZEN",
                  deposit_held_cents=5000000, deposit_applied_cents=0,
                  deposit_refunded_cents=0)
    assert_deposit_conserved(lease)
    return env, assessment


def test_the_inspector_may_not_apply_the_holdback_it_scored(api):
    """PRD §3.9: "The acting `X-User-ID` must differ from `inspected_by_user_id`, with the inspector's own attempt refused as `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/compensating_invariant/reversion_holdback_then_close_conserves_the_security_deposit_across_three_buckets
    """
    env, assessment = _inspected_reversion_short_of_the_standard(api)

    validate_error(
        api.apply_holdback(assessment["id"], f.holdback_payload(3500000),
                           make_asset_manager_headers("am-1")),
        ERR_SEGREGATION_OF_DUTIES,
        expected_status=403,
    )
    unchanged = validate_success(
        api.get_reversion_assessment(assessment["id"],
                                     make_asset_manager_headers("am-2"))
    )
    assert_fields(unchanged, status="INSPECTED")
    assert unchanged["holdback_cents"] is None
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(lease, deposit_held_cents=5000000, deposit_applied_cents=0,
                  deposit_refunded_cents=0)
    assert_deposit_conserved(lease)


def test_the_acknowledged_holdback_must_reconcile_and_may_be_applied_only_once(api):
    """PRD §3.9: "Where the premises fall short of the standard, the lessor takes a holdback out of the deposit."

    Design: Difficulty/compensating_invariant/reversion_holdback_then_close_conserves_the_security_deposit_across_three_buckets
    """
    env, assessment = _inspected_reversion_short_of_the_standard(api)
    accountant = make_accountant_headers("acct-1")

    validate_error(
        api.apply_holdback(assessment["id"], f.holdback_payload(3400000), accountant),
        ERR_AMOUNT_NOT_RECONCILED,
        expected_status=422,
    )
    assert validate_success(
        api.get_reversion_assessment(assessment["id"], accountant)
    )["status"] == "INSPECTED"

    applied = validate_success(
        api.apply_holdback(assessment["id"], f.holdback_payload(3500000), accountant)
    )
    assert_fields(applied, status="HOLDBACK_APPLIED", holdback_cents=3500000)
    after = fx.read_lease(api, env["lease_id"])
    assert_fields(after, deposit_held_cents=1500000, deposit_applied_cents=3500000,
                  deposit_refunded_cents=0, lease_status="EXPIRED")
    assert_deposit_conserved(after)

    validate_error(
        api.apply_holdback(assessment["id"], f.holdback_payload(3500000), accountant),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    still = fx.read_lease(api, env["lease_id"])
    assert_fields(still, deposit_held_cents=1500000, deposit_applied_cents=3500000,
                  deposit_refunded_cents=0)
    assert_deposit_conserved(still)


def test_closing_releases_the_post_holdback_balance_and_conserves_the_deposit(api):
    """PRD §3.9: "Both branches do the same work: `deposit_released_cents` is set to whatever the lease's `deposit_held_cents` currently is — which, on the holdback branch, is the figure remaining after the holdback was taken — that amount is added to the lease's `deposit_refunded_cents`, and `deposit_held_cents` becomes 0, preserving the deposit invariant exactly."

    Design: Difficulty/compensating_invariant/reversion_holdback_then_close_conserves_the_security_deposit_across_three_buckets
    """
    env, assessment = _inspected_reversion_short_of_the_standard(api)
    manager = make_asset_manager_headers("am-1")
    validate_success(
        api.apply_holdback(assessment["id"], f.holdback_payload(3500000),
                           make_accountant_headers("acct-1"))
    )

    closed = validate_success(api.close_assessment(assessment["id"], manager))
    assert_fields(closed, status="CLOSED", deposit_released_cents=1500000,
                  holdback_cents=3500000)
    reverted = fx.read_lease(api, env["lease_id"])
    assert_fields(reverted, lease_status="REVERTED", deposit_held_cents=0,
                  deposit_applied_cents=3500000, deposit_refunded_cents=1500000)
    assert_deposit_conserved(reverted)

    validate_error(
        api.close_assessment(assessment["id"], manager),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    final = fx.read_lease(api, env["lease_id"])
    assert_fields(final, deposit_held_cents=0, deposit_applied_cents=3500000,
                  deposit_refunded_cents=1500000)
    assert_deposit_conserved(final)


def _lease_in_arbitration_with_a_mortgage(api):
    """Insurance to 2027-01-01 so the priority-18 rule is satisfied, one RECORDED
    mortgage to request the certificate, and a revaluation referred to arbitration."""
    env = fx.standard_lease(api, "PIER-60")
    fx.file_insurance(api, env["lease_id"])
    mortgage = fx.record_senior_mortgage(api, env["lease_id"])
    reval, arbitration = fx.referred_revaluation(api, env["lease_id"], env["lessee_id"])
    assert reval["status"] == "ARBITRATION_REFERRED"
    assert_fields(fx.read_lease(api, env["lease_id"]),
                  rent_status="IN_ARBITRATION", insurance_status="ACTIVE")
    return env, mortgage, reval, arbitration


def test_estoppel_issuance_is_blocked_while_a_revaluation_sits_in_arbitration(api):
    """PRD §3.2: "A certificate may not be issued while any revaluation on the lease sits in `ARBITRATION_REFERRED`, because the rent is genuinely unsettled — that refusal is `ERR_CROSS_ENTITY_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/estoppel_certificate_blocked_while_a_revaluation_is_in_arbitration
    """
    env, mortgage, _reval, _arbitration = _lease_in_arbitration_with_a_mortgage(api)
    agent = make_mortgagee_agent_headers(mortgage["id"])
    pinned = fx.lease_version(api, env["lease_id"], agent)

    # The version supplied is current, so the refusal cannot be version pinning.
    validate_error(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], pinned), agent
        ),
        ERR_CROSS_ENTITY_BLOCKED,
        expected_status=409,
    )
    rows, meta = validate_paginated(
        api.list_estoppels(make_lessor_admin_headers(), {"lease_id": env["lease_id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert fx.lease_version(api, env["lease_id"], agent) == pinned


def test_the_award_clears_the_block_and_the_certificate_freezes_the_reset_rent(api):
    """PRD §3.2: "`certified_annual_base_rent_cents` snapshots the lease's `current_annual_base_rent_cents`, `certified_arrears_cents` snapshots its `arrears_balance_cents`, `certified_rent_status` snapshots its `rent_status`, and `certified_lease_version` records the lease's `version` as it stands *after* the issuance's own increment — a certificate pinned against version 5 therefore certifies a `certified_lease_version` of 6."

    Design: Difficulty/cross_entity_state_dependency/estoppel_certificate_blocked_while_a_revaluation_is_in_arbitration
    """
    env, mortgage, reval, arbitration = _lease_in_arbitration_with_a_mortgage(api)
    agent = make_mortgagee_agent_headers(mortgage["id"])
    blocked_version = fx.lease_version(api, env["lease_id"], agent)
    validate_error(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], blocked_version), agent
        ),
        ERR_CROSS_ENTITY_BLOCKED,
        expected_status=409,
    )

    fx.render_award(api, arbitration["id"], 13000000)
    resolved = validate_success(
        api.get_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(resolved, status="RESOLVED",
                  resolved_annual_base_rent_cents=14000000)
    cleared_version = fx.lease_version(api, env["lease_id"], agent)
    assert cleared_version == blocked_version + 1

    certificate = validate_success(
        api.issue_estoppel(
            f.estoppel_payload(env["lease_id"], mortgage["id"], cleared_version), agent
        ),
        expected_status=201,
    )
    assert_fields(
        certificate,
        status="ISSUED",
        certified_annual_base_rent_cents=14000000,
        certified_arrears_cents=0,
        certified_rent_status="RESET_APPLIED",
        certified_lease_version=cleared_version + 1,
    )
