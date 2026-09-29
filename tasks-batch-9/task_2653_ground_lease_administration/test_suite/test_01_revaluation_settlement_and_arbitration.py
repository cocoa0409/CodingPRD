"""Rent revaluation: appraisal exchange, midpoint settlement, baseball
arbitration, the single negotiation cycle and the two lease status axes."""

from test_helpers import (
    ERR_CROSS_ENTITY_BLOCKED,
    ERR_MAX_ROUNDS_REACHED,
    assert_appraisal_shape,
    assert_fields,
    factories as f,
    fixtures as fx,
    make_arbitrator_headers,
    make_ground_tenant_headers,
    make_lessor_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _exchanged_pair(api, premises_code):
    """One lessee, one lease, one revaluation exchanged at 14000000 / 10000000."""
    env = fx.standard_lease(api, premises_code)
    reval = fx.exchanged_revaluation(api, env["lease_id"], env["lessee_id"])
    return env, reval


def test_midpoint_settlement_writes_the_collar_clamped_midpoint(api):
    """PRD §3.3: "Its indicated rent is the arithmetic midpoint of the two exchanged appraisals: add `lessor_appraised_rent_cents` to `lessee_appraised_rent_cents`, divide by 2, and round half up to whole cents."

    Design: Difficulty/dual_variant_calc/revaluation_reset_midpoint_settlement_vs_arbitration_award
    """
    env, reval = _exchanged_pair(api, "PIER-40-A")
    assert reval["divergence_bps"] == 4000

    settled = validate_success(
        api.settle_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(
        settled,
        status="RESOLVED",
        resolution_method="MIDPOINT_SETTLEMENT",
        resolved_annual_base_rent_cents=12000000,
    )

    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(
        lease,
        current_annual_base_rent_cents=12000000,
        rent_status="RESET_APPLIED",
        lease_status="ACTIVE",
    )


def test_baseball_award_selects_the_closest_appraisal_rather_than_averaging(api):
    """PRD §3.3: "If the lessor's appraisal is strictly nearer, the indicated rent is `lessor_appraised_rent_cents` and `award_basis` is recorded as `CLOSEST_LESSOR`."

    Design: Difficulty/dual_variant_calc/revaluation_reset_midpoint_settlement_vs_arbitration_award
    """
    env, reval = _exchanged_pair(api, "PIER-40-B")

    arbitration = validate_success(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        expected_status=201,
    )
    awarded = validate_success(
        api.render_award(
            arbitration["id"],
            f.award_payload(13000000),
            make_arbitrator_headers("arb-neutral-1"),
        )
    )
    assert_fields(
        awarded, award_basis="CLOSEST_LESSOR", awarded_annual_rent_cents=14000000
    )

    resolved = validate_success(
        api.get_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(
        resolved,
        status="RESOLVED",
        resolution_method="ARBITRATION_AWARD",
        resolved_annual_base_rent_cents=14000000,
    )
    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(
        lease, current_annual_base_rent_cents=14000000, rent_status="RESET_APPLIED"
    )


def test_the_two_resolution_routes_price_identical_appraisals_differently(api):
    """PRD §3.3: "A revaluation that has reached `PROPOSALS_EXCHANGED` can be resolved in exactly two ways, and both end at the same place — a collar-clamped figure written into the lease's `current_annual_base_rent_cents` — but they select the pre-clamp figure differently, and for the same pair of appraisals they routinely produce different rents."

    Design: Difficulty/dual_variant_calc/revaluation_reset_midpoint_settlement_vs_arbitration_award
    """
    lessee = fx.create_lessee(api)
    lease_a = fx.create_lease(api, lessee["id"], "PIER-40-A")
    lease_b = fx.create_lease(api, lessee["id"], "PIER-40-B")

    reval_a = fx.exchanged_revaluation(api, lease_a["id"], lessee["id"])
    reval_b = fx.exchanged_revaluation(api, lease_b["id"], lessee["id"])
    assert reval_a["divergence_bps"] == 4000
    assert reval_b["divergence_bps"] == 4000

    validate_success(api.settle_revaluation(reval_a["id"], make_lessor_admin_headers()))
    arbitration = validate_success(
        api.refer_to_arbitration(
            reval_b["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        expected_status=201,
    )
    validate_success(
        api.render_award(
            arbitration["id"],
            f.award_payload(13000000),
            make_arbitrator_headers("arb-neutral-1"),
        )
    )

    rent_a = fx.read_lease(api, lease_a["id"])["current_annual_base_rent_cents"]
    rent_b = fx.read_lease(api, lease_b["id"])["current_annual_base_rent_cents"]
    assert rent_a == 12000000
    assert rent_b == 14000000
    assert rent_b - rent_a == 2000000


def test_opening_a_second_round_clears_the_exchanged_figures(api):
    """PRD §3.3: "Opening the round increments `round_number` by 1, clears `lessor_appraised_rent_cents`, `lessee_appraised_rent_cents` and `divergence_bps` back to null so that the new round's submissions must be lodged and exchanged afresh, and returns the revaluation `PROPOSALS_EXCHANGED → OPEN_FOR_APPRAISALS`."

    Design: Difficulty/non_linear_state_machine/revaluation_round_cycle_reopens_then_refuses_a_third_round
    """
    env, reval = _exchanged_pair(api, "PIER-47")
    assert_fields(reval, status="PROPOSALS_EXCHANGED", round_number=1, divergence_bps=4000)

    reopened = validate_success(
        api.open_next_round(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(reopened, status="OPEN_FOR_APPRAISALS", round_number=2)
    assert reopened["lessor_appraised_rent_cents"] is None
    assert reopened["lessee_appraised_rent_cents"] is None
    assert reopened["divergence_bps"] is None


def test_superseded_round_submissions_are_retained_and_immutable(api):
    """PRD §3.3: "Because a superseded round's submissions are retained but excluded from every later computation, the submission list — narrowable by `revaluation_id`, by `appointed_by` and by `round_number` — is the only channel through which the history of earlier rounds can be discovered."

    Design: Difficulty/non_linear_state_machine/revaluation_round_cycle_reopens_then_refuses_a_third_round
    """
    env, reval = _exchanged_pair(api, "PIER-47")
    validate_success(api.open_next_round(reval["id"], make_lessor_admin_headers()))

    fx.lodge_both_appraisals(
        api, reval["id"], env["lessee_id"],
        lessor_cents=13500000, lessee_cents=11000000, lessor_method="RESIDUAL_LAND",
    )

    rows, meta = validate_paginated(
        api.list_appraisals(
            make_lessor_admin_headers(), {"revaluation_id": reval["id"]}
        )
    )
    assert meta["total_count"] == 4
    assert sorted(row["round_number"] for row in rows) == [1, 1, 2, 2]
    for row in rows:
        assert_appraisal_shape(row)


def test_a_third_negotiation_round_is_refused_as_max_rounds_reached(api):
    """PRD §3.3: "A further round attempted once the divergence has narrowed to 1,000 basis points or less is refused with `ERR_DIVERGENCE_BELOW_THRESHOLD`, and a third round is refused with `ERR_MAX_ROUNDS_REACHED`."

    Design: Difficulty/non_linear_state_machine/revaluation_round_cycle_reopens_then_refuses_a_third_round
    """
    env, reval = _exchanged_pair(api, "PIER-47")
    validate_success(api.open_next_round(reval["id"], make_lessor_admin_headers()))
    fx.lodge_both_appraisals(
        api, reval["id"], env["lessee_id"],
        lessor_cents=13500000, lessee_cents=11000000, lessor_method="RESIDUAL_LAND",
    )
    exchanged = validate_success(
        api.exchange_proposals(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(
        exchanged,
        status="PROPOSALS_EXCHANGED",
        round_number=2,
        lessor_appraised_rent_cents=13500000,
        lessee_appraised_rent_cents=11000000,
        divergence_bps=2273,
    )

    validate_error(
        api.open_next_round(reval["id"], make_lessor_admin_headers()),
        ERR_MAX_ROUNDS_REACHED,
        expected_status=409,
    )
    unchanged = validate_success(
        api.get_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(unchanged, status="PROPOSALS_EXCHANGED", round_number=2)


def test_settlement_after_a_second_round_uses_the_round_two_midpoint(api):
    """PRD §3.3: "The exchange demands exactly one `LESSOR` submission and one `LESSEE` submission whose `round_number` equals the revaluation's current `round_number`; an exchange attempted without both is refused with `ERR_APPRAISALS_INCOMPLETE`."

    Design: Difficulty/non_linear_state_machine/revaluation_round_cycle_reopens_then_refuses_a_third_round
    """
    env, reval = _exchanged_pair(api, "PIER-47")
    validate_success(api.open_next_round(reval["id"], make_lessor_admin_headers()))
    fx.lodge_both_appraisals(
        api, reval["id"], env["lessee_id"],
        lessor_cents=13500000, lessee_cents=11000000, lessor_method="RESIDUAL_LAND",
    )
    validate_success(api.exchange_proposals(reval["id"], make_lessor_admin_headers()))

    settled = validate_success(
        api.settle_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert settled["resolved_annual_base_rent_cents"] == 12250000
    assert settled["resolved_annual_base_rent_cents"] != 12000000

    lease = fx.read_lease(api, env["lease_id"])
    assert_fields(
        lease, current_annual_base_rent_cents=12250000, rent_status="RESET_APPLIED"
    )


def test_referral_moves_the_rent_axis_and_leaves_the_tenancy_axis_alone(api):
    """PRD §2.11: "A lease may sit in `IN_DEFAULT` on the tenancy axis while its rent axis sits in `IN_ARBITRATION`, and curing the default returns the tenancy axis to `ACTIVE` without touching the rent axis at all."

    Design: Difficulty/non_linear_state_machine/lease_parallel_axes_tenancy_and_rent_move_independently
    """
    env, reval = _exchanged_pair(api, "PIER-46")
    fx.add_arrears(api, env["lease_id"], 1000000)

    before = fx.read_lease(api, env["lease_id"])
    assert_fields(before, lease_status="ACTIVE", rent_status="REVALUATION_OPEN")

    validate_success(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        expected_status=201,
    )
    after_referral = fx.read_lease(api, env["lease_id"])
    assert_fields(after_referral, lease_status="ACTIVE", rent_status="IN_ARBITRATION")


def test_default_and_cure_move_only_the_tenancy_axis(api):
    """PRD §2.11: "The two axes evolve independently."

    Design: Difficulty/non_linear_state_machine/lease_parallel_axes_tenancy_and_rent_move_independently
    """
    env, reval = _exchanged_pair(api, "PIER-46")
    fx.add_arrears(api, env["lease_id"], 1000000)
    validate_success(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        expected_status=201,
    )

    notice = fx.served_default_notice(
        api, env["lease_id"], "MONETARY_RENT_ARREARS", 1000000, user_id="acct-1"
    )
    in_default = fx.read_lease(api, env["lease_id"])
    assert_fields(in_default, lease_status="IN_DEFAULT", rent_status="IN_ARBITRATION")

    cured = validate_success(
        api.lessee_cure(
            notice["id"],
            f.lessee_cure_payload("2026-08-02T00:00:00Z", 1000000),
            make_ground_tenant_headers(env["lessee_id"]),
        )
    )
    assert_fields(cured, status="LESSEE_CURED", cured_by="LESSEE")

    restored = fx.read_lease(api, env["lease_id"])
    assert_fields(
        restored,
        lease_status="ACTIVE",
        rent_status="IN_ARBITRATION",
        arrears_balance_cents=0,
    )


def test_the_award_cascade_touches_the_rent_axis_only(api):
    """PRD §2.11: "Nothing on the rent axis ever moves the tenancy axis."

    Design: Difficulty/non_linear_state_machine/lease_parallel_axes_tenancy_and_rent_move_independently
    """
    env, reval = _exchanged_pair(api, "PIER-46")
    fx.add_arrears(api, env["lease_id"], 1000000)
    arbitration = validate_success(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        expected_status=201,
    )
    notice = fx.served_default_notice(
        api, env["lease_id"], "MONETARY_RENT_ARREARS", 1000000, user_id="acct-1"
    )
    validate_success(
        api.lessee_cure(
            notice["id"],
            f.lessee_cure_payload("2026-08-02T00:00:00Z", 1000000),
            make_ground_tenant_headers(env["lessee_id"]),
        )
    )

    validate_success(
        api.render_award(
            arbitration["id"],
            f.award_payload(13000000),
            make_arbitrator_headers("arb-neutral-1"),
        )
    )
    final = fx.read_lease(api, env["lease_id"])
    assert_fields(
        final,
        lease_status="ACTIVE",
        rent_status="RESET_APPLIED",
        current_annual_base_rent_cents=14000000,
    )
    resolved = validate_success(
        api.get_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert_fields(resolved, status="RESOLVED", resolution_method="ARBITRATION_AWARD")


def test_arbitration_referral_is_blocked_while_the_lease_is_in_default(api):
    """PRD §3.3: "A referral is also blocked while the lease's tenancy axis sits in `IN_DEFAULT`, which is refused with `ERR_CROSS_ENTITY_BLOCKED`, and only one proceeding may exist per revaluation, a second being refused with `ERR_DUPLICATE_RECORD`."

    Design: Difficulty/cross_entity_state_dependency/arbitration_referral_blocked_while_the_lease_sits_in_default
    """
    env, reval = _exchanged_pair(api, "PIER-58")
    fx.add_arrears(api, env["lease_id"], 1000000)
    fx.served_default_notice(
        api, env["lease_id"], "MONETARY_RENT_ARREARS", 1000000, user_id="acct-1"
    )

    blocked = fx.read_lease(api, env["lease_id"])
    assert_fields(blocked, lease_status="IN_DEFAULT", rent_status="REVALUATION_OPEN")

    validate_error(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        ERR_CROSS_ENTITY_BLOCKED,
        expected_status=409,
    )
    still_exchanged = validate_success(
        api.get_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert still_exchanged["status"] == "PROPOSALS_EXCHANGED"

    # PRD §4: GET /portfolio/arbitrations authorises LessorAdmin, GroundTenant
    # and Arbitrator only — an AssetManager read is a legitimate 403.
    rows, meta = validate_paginated(
        api.list_arbitrations(
            make_lessor_admin_headers(), {"revaluation_id": reval["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_curing_the_default_unblocks_the_identical_referral(api):
    """PRD §3.3: "The referral creates a proceeding in status `REFERRED`, moves the revaluation `PROPOSALS_EXCHANGED → ARBITRATION_REFERRED`, and moves the lease's rent axis `REVALUATION_OPEN → IN_ARBITRATION`."

    Design: Difficulty/cross_entity_state_dependency/arbitration_referral_blocked_while_the_lease_sits_in_default
    """
    env, reval = _exchanged_pair(api, "PIER-58")
    fx.add_arrears(api, env["lease_id"], 1000000)
    notice = fx.served_default_notice(
        api, env["lease_id"], "MONETARY_RENT_ARREARS", 1000000, user_id="acct-1"
    )
    validate_error(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        ERR_CROSS_ENTITY_BLOCKED,
        expected_status=409,
    )

    validate_success(
        api.lessee_cure(
            notice["id"],
            f.lessee_cure_payload("2026-08-02T00:00:00Z", 1000000),
            make_ground_tenant_headers(env["lessee_id"]),
        )
    )
    cured_lease = fx.read_lease(api, env["lease_id"])
    assert_fields(
        cured_lease,
        lease_status="ACTIVE",
        arrears_balance_cents=0,
        rent_status="REVALUATION_OPEN",
    )

    arbitration = validate_success(
        api.refer_to_arbitration(
            reval["id"], f.referral_payload("arb-neutral-1"), make_lessor_admin_headers()
        ),
        expected_status=201,
    )
    assert_fields(arbitration, status="REFERRED", arbitrator_user_id="arb-neutral-1")

    referred = validate_success(
        api.get_revaluation(reval["id"], make_lessor_admin_headers())
    )
    assert referred["status"] == "ARBITRATION_REFERRED"
    assert fx.read_lease(api, env["lease_id"])["rent_status"] == "IN_ARBITRATION"
