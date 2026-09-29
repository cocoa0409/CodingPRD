"""Casualty and condemnation proceeds: the four-bucket waterfall, the two
allocation methods, the priority-ordered mortgage payoff, the shrinking input
set an extinguishment leaves behind and the compensating rescission."""

from test_helpers import (
    ERR_INVALID_STATE,
    assert_fields,
    assert_proceeds_conserved,
    fixtures as fx,
    make_accountant_headers,
    make_lessor_admin_headers,
    validate_error,
    validate_success,
)

RESCIND = {"reason_code": "POSTED_IN_ERROR"}


def _two_leases_with_one_condemnation_each(api):
    """Identical ledgers on both leases: 1000000 of arrears and two mortgages at
    3000000 and 2000000, with a 20000000 condemnation pool adjusted under
    BONUS_VALUE on C and PRO_RATA_VALUE on D."""
    lessee = fx.create_lessee(api)
    world = {}
    for label, premises_code, method in (
        ("c", "PIER-41-C", "BONUS_VALUE"),
        ("d", "PIER-41-D", "PRO_RATA_VALUE"),
    ):
        lease = fx.create_lease(api, lessee["id"], premises_code)
        fx.add_arrears(api, lease["id"], 1000000)
        senior = fx.record_senior_mortgage(api, lease["id"])
        mezz = fx.record_mezz_mortgage(api, lease["id"])
        event = fx.adjusted_loss_event(
            api, lease["id"], 20000000, method, 0,
            event_type="CONDEMNATION", scope_code="PARTIAL",
            occurred_at="2026-07-01T00:00:00Z",
            damage_estimate_cents=20000000, damaged_area_sqft=5000,
        )
        world[label] = {"lease": lease, "senior": senior, "mezz": mezz,
                        "event": event}
    return lessee, world


def test_bonus_value_shares_the_pool_on_relative_value(api):
    """PRD §3.8: "Under `BONUS_VALUE` the share is a pure value split that ignores how much term is left: multiply the lease's `improvements_value_cents` by 10,000, divide by the sum of `improvements_value_cents` and `reversion_land_value_cents`, and round half up to whole basis points."

    Design: Difficulty/dual_variant_calc/condemnation_proceeds_bonus_value_vs_pro_rata_share
    """
    _lessee, world = _two_leases_with_one_condemnation_each(api)
    lease_c = world["c"]

    allocated = validate_success(
        api.allocate_proceeds(lease_c["event"]["id"],
                              make_accountant_headers("acct-1"))
    )
    assert_fields(
        allocated,
        status="ALLOCATED",
        lessee_share_bps=6000,
        allocated_arrears_cents=1000000,
        allocated_mortgagee_cents=5000000,
        allocated_lessee_cents=12000000,
        allocated_lessor_cents=2000000,
    )
    assert_proceeds_conserved(allocated)
    assert allocated["allocation_detail"] == [
        {"mortgage_id": lease_c["senior"]["id"], "amount_cents": 3000000},
        {"mortgage_id": lease_c["mezz"]["id"], "amount_cents": 2000000},
    ]
    assert fx.read_lease(api, lease_c["lease"]["id"])["arrears_balance_cents"] == 0


def test_pro_rata_value_shares_the_pool_on_the_remaining_term(api):
    """PRD §3.8: "Under `PRO_RATA_VALUE` the share is a pure term split that ignores relative values: count the whole days from the lease's `commencement_date` to its `expiration_date` as the total term, count the whole days from the logical clock's current instant to `expiration_date` as the remaining term, multiply the remaining days by 10,000, divide by the total days, and round half up to whole basis points; day counts use a 365-day year basis."

    Design: Difficulty/dual_variant_calc/condemnation_proceeds_bonus_value_vs_pro_rata_share
    """
    _lessee, world = _two_leases_with_one_condemnation_each(api)
    lease_d = world["d"]

    allocated = validate_success(
        api.allocate_proceeds(lease_d["event"]["id"],
                              make_accountant_headers("acct-1"))
    )
    # 15859 of 18263 days remain at the default clock instant.
    assert_fields(
        allocated,
        lessee_share_bps=8684,
        allocated_arrears_cents=1000000,
        allocated_mortgagee_cents=5000000,
        allocated_lessee_cents=14000000,
        allocated_lessor_cents=0,
    )
    assert_proceeds_conserved(allocated)
    assert fx.read_lease(api, lease_d["lease"]["id"])["arrears_balance_cents"] == 0


def test_bucket_three_is_computed_on_the_full_pool_then_capped_by_the_remainder(api):
    """PRD §3.8: "The share is computed on the **full** pool, not on what bucket two left, and only then capped by what remains."

    Design: Difficulty/dual_variant_calc/condemnation_proceeds_bonus_value_vs_pro_rata_share
    """
    _lessee, world = _two_leases_with_one_condemnation_each(api)
    accountant = make_accountant_headers("acct-1")

    bonus = validate_success(
        api.allocate_proceeds(world["c"]["event"]["id"], accountant)
    )
    pro_rata = validate_success(
        api.allocate_proceeds(world["d"]["event"]["id"], accountant)
    )
    # Identical ledgers, identical pools, different bucket three and bucket four.
    assert bonus["allocated_arrears_cents"] == pro_rata["allocated_arrears_cents"]
    assert bonus["allocated_mortgagee_cents"] == pro_rata["allocated_mortgagee_cents"]
    assert bonus["allocated_lessee_cents"] != pro_rata["allocated_lessee_cents"]
    # 20000000 x 8684 bps is 17368000, capped by the 14000000 the pool still held.
    assert pro_rata["allocated_lessee_cents"] == 14000000
    assert pro_rata["allocated_lessor_cents"] == 0
    assert_proceeds_conserved(bonus)
    assert_proceeds_conserved(pro_rata)


def _two_condemnations_on_one_encumbered_lease(api):
    """No arrears, a 3000000 senior and a 2000000 mezzanine, and two condemnation
    events adjusted at 3000000 and then at 2000000."""
    env = fx.standard_lease(api, "PIER-51")
    senior = fx.record_senior_mortgage(api, env["lease_id"])
    mezz = fx.record_mezz_mortgage(api, env["lease_id"])
    first = fx.adjusted_loss_event(
        api, env["lease_id"], 3000000, "BONUS_VALUE", 0,
        event_type="CONDEMNATION", scope_code="PARTIAL",
        occurred_at="2026-07-01T00:00:00Z",
        damage_estimate_cents=3000000, damaged_area_sqft=1000,
    )
    return env, senior, mezz, first


def test_a_pool_that_runs_dry_still_records_a_zero_cent_entry_for_the_junior(api):
    """PRD §3.8: "Note that a low-priority mortgage can legitimately receive an entry of 0 cents where the pool ran dry before reaching it."

    Design: Difficulty/transitive_cascade/allocation_extinguishes_senior_mortgage_and_shrinks_the_next_waterfall_input_set
    """
    env, senior, mezz, first = _two_condemnations_on_one_encumbered_lease(api)
    admin = make_lessor_admin_headers()

    allocated = validate_success(
        api.allocate_proceeds(first["id"], make_accountant_headers("acct-1"))
    )
    assert allocated["allocation_detail"] == [
        {"mortgage_id": senior["id"], "amount_cents": 3000000},
        {"mortgage_id": mezz["id"], "amount_cents": 0},
    ]
    assert_fields(
        allocated,
        status="ALLOCATED",
        allocated_arrears_cents=0,
        allocated_mortgagee_cents=3000000,
        lessee_share_bps=6000,
        allocated_lessee_cents=0,
        allocated_lessor_cents=0,
    )
    assert_proceeds_conserved(allocated)

    assert_fields(
        validate_success(api.get_mortgage(senior["id"], admin)),
        status="EXTINGUISHED", outstanding_principal_cents=0,
    )
    assert_fields(
        validate_success(api.get_mortgage(mezz["id"], admin)),
        status="RECORDED", outstanding_principal_cents=2000000,
    )


def test_an_extinguished_mortgage_drops_out_of_the_next_waterfall_input_set(api):
    """PRD §3.8: "Assemble the mortgages on the lease whose status is `RECORDED`, `NOTICE_SERVED`, `CURING` or `NEW_LEASE_ELIGIBLE`, ordered by `priority_rank` ascending and then by `created_at` ascending; mortgages in `EXTINGUISHED` or `NEW_LEASE_ELECTED` are excluded."

    Design: Difficulty/transitive_cascade/allocation_extinguishes_senior_mortgage_and_shrinks_the_next_waterfall_input_set
    """
    env, senior, mezz, first = _two_condemnations_on_one_encumbered_lease(api)
    accountant = make_accountant_headers("acct-1")
    admin = make_lessor_admin_headers()
    validate_success(api.allocate_proceeds(first["id"], accountant))

    second = fx.adjusted_loss_event(
        api, env["lease_id"], 2000000, "BONUS_VALUE", 0,
        event_type="CONDEMNATION", scope_code="PARTIAL",
        occurred_at="2026-07-15T00:00:00Z",
        damage_estimate_cents=2000000, damaged_area_sqft=800,
    )
    allocated = validate_success(api.allocate_proceeds(second["id"], accountant))

    # The senior is gone, so the second waterfall walks a one-row input set.
    assert allocated["allocation_detail"] == [
        {"mortgage_id": mezz["id"], "amount_cents": 2000000}
    ]
    assert_fields(
        allocated,
        allocated_arrears_cents=0,
        allocated_mortgagee_cents=2000000,
        allocated_lessee_cents=0,
        allocated_lessor_cents=0,
    )
    assert_proceeds_conserved(allocated)
    assert_fields(
        validate_success(api.get_mortgage(mezz["id"], admin)),
        status="EXTINGUISHED", outstanding_principal_cents=0,
    )
    summary = validate_success(api.get_rent_summary(env["lease_id"], admin))
    assert summary["open_mortgage_principal_cents"] == 0


def _allocated_condemnation_with_arrears_and_two_mortgages(api):
    """1000000 of arrears, a 3000000 senior and a 2000000 mezzanine, and a
    6000000 condemnation pool allocated under BONUS_VALUE."""
    env = fx.standard_lease(api, "PIER-63")
    fx.add_arrears(api, env["lease_id"], 1000000)
    senior = fx.record_senior_mortgage(api, env["lease_id"])
    mezz = fx.record_mezz_mortgage(api, env["lease_id"])
    event = fx.adjusted_loss_event(
        api, env["lease_id"], 6000000, "BONUS_VALUE", 0,
        event_type="CONDEMNATION", scope_code="PARTIAL",
        occurred_at="2026-07-01T00:00:00Z",
        damage_estimate_cents=6000000, damaged_area_sqft=2000,
    )
    version_before = fx.lease_version(api, env["lease_id"])
    allocated = validate_success(
        api.allocate_proceeds(event["id"], make_accountant_headers("acct-1"))
    )
    assert_fields(
        allocated,
        status="ALLOCATED",
        lessee_share_bps=6000,
        allocated_arrears_cents=1000000,
        allocated_mortgagee_cents=5000000,
        allocated_lessee_cents=0,
        allocated_lessor_cents=0,
    )
    assert_proceeds_conserved(allocated)
    return env, senior, mezz, event, version_before


def test_rescission_restores_the_arrears_and_every_mortgage_principal_exactly(api):
    """PRD §3.8: "Rescission adds `allocated_arrears_cents` back to the lease's `arrears_balance_cents`; restores each mortgage named in `allocation_detail` by adding its `amount_cents` back to that mortgage's `outstanding_principal_cents`, **replaying the list in reverse order** so that any mortgage driven to `EXTINGUISHED` by the allocation returns to the status it held before it; returns all four of `allocated_arrears_cents`, `allocated_mortgagee_cents`, `allocated_lessee_cents` and `allocated_lessor_cents` to 0; clears `lessee_share_bps` and empties `allocation_detail`; and increments the lease `version` by one."

    Design: Difficulty/compensating_invariant/condemnation_allocation_rescinded_restores_arrears_and_every_mortgage_principal_exactly
    """
    env, senior, mezz, event, version_before = (
        _allocated_condemnation_with_arrears_and_two_mortgages(api)
    )
    admin = make_lessor_admin_headers()
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 0

    rescinded = validate_success(
        api.rescind_allocation(event["id"], dict(RESCIND),
                               make_accountant_headers("acct-1"))
    )
    assert_fields(
        rescinded,
        status="ALLOCATION_RESCINDED",
        allocated_arrears_cents=0,
        allocated_mortgagee_cents=0,
        allocated_lessee_cents=0,
        allocated_lessor_cents=0,
    )
    assert rescinded["lessee_share_bps"] is None
    assert rescinded["allocation_detail"] == []

    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 1000000
    assert_fields(
        validate_success(api.get_mortgage(senior["id"], admin)),
        status="RECORDED", outstanding_principal_cents=3000000,
    )
    assert_fields(
        validate_success(api.get_mortgage(mezz["id"], admin)),
        status="RECORDED", outstanding_principal_cents=2000000,
    )
    # One increment for the allocation, one for the compensating rescission.
    assert fx.lease_version(api, env["lease_id"]) == version_before + 2


def test_a_second_rescission_is_refused_and_moves_no_money(api):
    """PRD §3.8: "An allocation posted in error is reversed by rescission, a compensating action available to a `LeaseAccountant` on an event in `ALLOCATED`, supplying a `reason_code`."

    Design: Difficulty/compensating_invariant/condemnation_allocation_rescinded_restores_arrears_and_every_mortgage_principal_exactly
    """
    env, senior, mezz, event, version_before = (
        _allocated_condemnation_with_arrears_and_two_mortgages(api)
    )
    accountant = make_accountant_headers("acct-1")
    admin = make_lessor_admin_headers()
    validate_success(api.rescind_allocation(event["id"], dict(RESCIND), accountant))

    validate_error(
        api.rescind_allocation(event["id"], dict(RESCIND), accountant),
        ERR_INVALID_STATE,
        expected_status=409,
    )
    still_rescinded = validate_success(api.get_loss_event(event["id"], admin))
    assert_fields(still_rescinded, status="ALLOCATION_RESCINDED",
                  allocated_arrears_cents=0, allocated_mortgagee_cents=0)
    assert still_rescinded["allocation_detail"] == []

    # The refusal is not a second restoration: nothing is credited twice.
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 1000000
    assert validate_success(
        api.get_mortgage(senior["id"], admin)
    )["outstanding_principal_cents"] == 3000000
    assert validate_success(
        api.get_mortgage(mezz["id"], admin)
    )["outstanding_principal_cents"] == 2000000
    assert fx.lease_version(api, env["lease_id"]) == version_before + 2


def test_the_re_run_after_rescission_reproduces_the_split_exactly(api):
    """PRD §3.8: "From there the waterfall may be re-run against the current ledger — `ALLOCATION_RESCINDED → ALLOCATED` — and the re-run may legitimately use a different `allocation_method` and therefore produce a different split."

    Design: Difficulty/compensating_invariant/condemnation_allocation_rescinded_restores_arrears_and_every_mortgage_principal_exactly
    """
    env, senior, mezz, event, version_before = (
        _allocated_condemnation_with_arrears_and_two_mortgages(api)
    )
    accountant = make_accountant_headers("acct-1")
    admin = make_lessor_admin_headers()
    validate_success(api.rescind_allocation(event["id"], dict(RESCIND), accountant))

    rerun = validate_success(api.allocate_proceeds(event["id"], accountant))
    assert_fields(
        rerun,
        status="ALLOCATED",
        lessee_share_bps=6000,
        allocated_arrears_cents=1000000,
        allocated_mortgagee_cents=5000000,
        allocated_lessee_cents=0,
        allocated_lessor_cents=0,
    )
    assert rerun["allocation_detail"] == [
        {"mortgage_id": senior["id"], "amount_cents": 3000000},
        {"mortgage_id": mezz["id"], "amount_cents": 2000000},
    ]
    assert_proceeds_conserved(rerun)
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 0
    for mortgage_id in (senior["id"], mezz["id"]):
        assert_fields(
            validate_success(api.get_mortgage(mortgage_id, admin)),
            status="EXTINGUISHED", outstanding_principal_cents=0,
        )
    assert fx.lease_version(api, env["lease_id"]) == version_before + 3
