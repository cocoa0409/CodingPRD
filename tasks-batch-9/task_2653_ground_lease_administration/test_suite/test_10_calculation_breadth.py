"""Calculation breadth: the collar clamp at both bounds and inside them, the
sublease inclusion base's status filter, the cure-window day constants and the
proceeds waterfall's bucket order."""

from test_helpers import (
    assert_fields,
    assert_instant,
    factories as f,
    fixtures as fx,
    make_accountant_headers,
    make_asset_manager_headers,
    make_lessor_admin_headers,
    validate_success,
)


def test_the_collar_clamps_the_midpoint_at_the_floor_and_at_the_ceiling(api):
    """PRD §3.3: "Step four clamps: the indicated rent is first raised to the collar floor if it falls below it, and the result is then lowered to the collar ceiling if it exceeds it."

    Design: Corner/calculations/revaluation_indicated_rent_clamped_by_both_collar_bounds
    """
    lessee = fx.create_lessee(api)
    admin = make_lessor_admin_headers()
    lease_f = fx.create_lease(api, lessee["id"], "PIER-95")
    lease_c = fx.create_lease(api, lessee["id"], "PIER-96")

    reval_f = fx.exchanged_revaluation(
        api, lease_f["id"], lessee["id"],
        lessor_cents=10400000, lessee_cents=10000000,
    )
    reval_c = fx.exchanged_revaluation(
        api, lease_c["id"], lessee["id"],
        lessor_cents=30000000, lessee_cents=20000000,
    )
    assert reval_f["divergence_bps"] == 400
    assert reval_c["divergence_bps"] == 5000

    floored = validate_success(api.settle_revaluation(reval_f["id"], admin))
    assert_fields(
        floored,
        resolution_method="MIDPOINT_SETTLEMENT",
        resolved_annual_base_rent_cents=11000000,
    )
    assert_fields(
        fx.read_lease(api, lease_f["id"]),
        current_annual_base_rent_cents=11000000,
        rent_status="RESET_APPLIED",
    )

    capped = validate_success(api.settle_revaluation(reval_c["id"], admin))
    assert capped["resolved_annual_base_rent_cents"] == 15000000
    assert_fields(
        fx.read_lease(api, lease_c["id"]),
        current_annual_base_rent_cents=15000000,
        rent_status="RESET_APPLIED",
    )


def test_a_midpoint_inside_the_collar_is_written_through_unclamped(api):
    """PRD §3.3: "The collar base is always the snapshot, never the lease's live `current_annual_base_rent_cents`."

    Design: Corner/calculations/revaluation_midpoint_inside_the_collar_is_left_unclamped
    """
    env = fx.standard_lease(api, "PIER-97")
    admin = make_lessor_admin_headers()
    reval = fx.exchanged_revaluation(
        api, env["lease_id"], env["lessee_id"],
        lessor_cents=12000000, lessee_cents=10500000,
    )
    assert reval["divergence_bps"] == 1429

    settled = validate_success(api.settle_revaluation(reval["id"], admin))
    assert_fields(
        settled,
        status="RESOLVED",
        resolution_method="MIDPOINT_SETTLEMENT",
        resolved_annual_base_rent_cents=11250000,
    )

    summary = validate_success(api.get_rent_summary(env["lease_id"], admin))
    assert summary["current_annual_base_rent_cents"] == 11250000
    assert_instant(
        fx.read_lease(api, env["lease_id"])["next_revaluation_date"],
        "2030-01-01T00:00:00Z",
    )


SUB_TERM = {"term_start": "2027-01-01T00:00:00Z", "term_end": "2030-01-01T00:00:00Z"}


def test_only_active_subleases_enter_the_percentage_rent_inclusion_base(api):
    """PRD §3.1: "A computed rent-summary read exists for lenders and for internal diligence: it reports `current_annual_base_rent_cents`, `percentage_rent_sublease_base_cents`, `arrears_balance_cents`, `gfa_allocated_sqft`, `gfa_unallocated_sqft`, `deposit_held_cents`, `deposit_applied_cents`, `deposit_refunded_cents`, an `active_sublease_count` giving the number of subleases on the lease currently in status `ACTIVE`, and an `open_mortgage_principal_cents` giving the summed `outstanding_principal_cents` of the lease's mortgages that have not been extinguished or replaced by a new lease."

    Design: Corner/calculations/sublease_inclusion_base_counts_only_active_subleases
    """
    env = fx.standard_lease(api, "PIER-98")
    manager = make_asset_manager_headers("am-1")

    granted_one = fx.consented_sublease(
        api, env["lease_id"], env["lessee_id"], "UNIT-A", 12000000,
        sublet_area_sqft=50000, transferee_legal_name="Pier Market Grocers LLC",
        **SUB_TERM,
    )
    assert_fields(
        granted_one,
        status="CONSENT_GRANTED",
        allocable_base_rent_cents=2500000,
        transfer_fee_gross_cents=4750000,
        admin_charge_cents=118750,
        late_surcharge_cents=0,
        total_transfer_fee_cents=4868750,
    )
    granted_two = fx.consented_sublease(
        api, env["lease_id"], env["lessee_id"], "UNIT-B", 8000000,
        sublet_area_sqft=50000, transferee_legal_name="Longshore Coffee Co",
        **SUB_TERM,
    )
    assert granted_two["status"] == "CONSENT_GRANTED"

    submitted_three = validate_success(
        api.create_transfer(
            f.sublease_payload(
                env["lease_id"], "UNIT-C", 5000000, sublet_area_sqft=20000,
                transferee_legal_name="Dockside Fitness LLC", **SUB_TERM
            ),
            env["tenant"],
        ),
        expected_status=201,
    )
    denied = validate_success(
        api.decide_transfer(
            submitted_three["id"],
            f.decision_payload("DENY", denial_reason_code="USE_INCOMPATIBLE"),
            manager,
        )
    )
    assert denied["status"] == "CONSENT_DENIED"
    for field in (
        "allocable_base_rent_cents", "transfer_fee_gross_cents",
        "admin_charge_cents", "late_surcharge_cents", "total_transfer_fee_cents",
    ):
        assert denied[field] is None, field

    assert fx.read_lease(api, env["lease_id"])[
        "percentage_rent_sublease_base_cents"] == 0

    activated = validate_success(
        api.pay_transfer_fee(
            granted_one["id"], f.fee_payment_payload(4868750), env["tenant"]
        )
    )
    assert_fields(activated, status="ACTIVE", transfer_fee_paid_cents=4868750)
    assert fx.read_lease(api, env["lease_id"])[
        "percentage_rent_sublease_base_cents"] == 6000000

    summary = validate_success(
        api.get_rent_summary(env["lease_id"], make_accountant_headers("acct-1"))
    )
    assert_fields(summary, active_sublease_count=1,
                  percentage_rent_sublease_base_cents=6000000)


def test_the_cure_window_length_is_selected_by_the_default_ground(api):
    """PRD §3.7: "The tenant's window length depends on the ground: 10 whole days for either of the two monetary grounds, 15 whole days for `INSURANCE_LAPSE`, and 30 whole days for `UNPERMITTED_USE` or `UNAUTHORIZED_TRANSFER`."

    Design: Corner/calculations/cure_window_days_are_selected_by_default_type
    """
    lessee = fx.create_lessee(api)
    lease_a = fx.create_lease(api, lessee["id"], "PIER-99")
    lease_b = fx.create_lease(api, lessee["id"], "PIER-100")
    fx.record_senior_mortgage(api, lease_b["id"], cure_extension_days=45)
    fx.add_arrears(api, lease_b["id"], 2000000)

    notice_a = validate_success(
        api.serve_default_notice(
            lease_a["id"], f.default_notice_payload("UNPERMITTED_USE"),
            make_asset_manager_headers("am-1"),
        ),
        expected_status=201,
    )
    assert_fields(
        notice_a,
        status="SERVED",
        served_at="2026-08-01T00:00:00Z",
        lessee_cure_deadline="2026-08-31T00:00:00Z",
    )
    assert notice_a["mortgagee_cure_deadline"] is None

    notice_b = validate_success(
        api.serve_default_notice(
            lease_b["id"],
            f.default_notice_payload("PERCENTAGE_RENT_UNDERPAYMENT", 2000000),
            make_accountant_headers("acct-1"),
        ),
        expected_status=201,
    )
    assert_fields(
        notice_b,
        status="SERVED",
        served_at="2026-08-01T00:00:00Z",
        lessee_cure_deadline="2026-08-11T00:00:00Z",
        mortgagee_cure_deadline="2026-09-25T00:00:00Z",
    )

    for lease_id in (lease_a["id"], lease_b["id"]):
        assert fx.read_lease(api, lease_id)["lease_status"] == "IN_DEFAULT"


def test_the_waterfall_pays_arrears_then_lenders_then_caps_the_lessee_share(api):
    """PRD §3.8: "Walk that list in order, paying each mortgage whichever is smaller of the remaining pool and its `outstanding_principal_cents`, appending a record of `mortgage_id` and `amount_cents` to `allocation_detail` **in the order paid**, and subtracting each payment from the remaining pool."

    Design: Corner/calculations/award_waterfall_fills_buckets_in_order_and_the_residual_absorbs_the_rest
    """
    env = fx.standard_lease(api, "PIER-101")
    admin = make_lessor_admin_headers()
    senior = fx.record_senior_mortgage(
        api, env["lease_id"], original_principal_cents=2000000
    )
    mezz = fx.record_mezz_mortgage(
        api, env["lease_id"], original_principal_cents=500000
    )
    fx.add_arrears(api, env["lease_id"], 1000000)
    event = fx.adjusted_loss_event(
        api, env["lease_id"], 10000000, "BONUS_VALUE",
        event_type="CONDEMNATION", damage_estimate_cents=10000000,
        damaged_area_sqft=30000,
    )

    allocated = validate_success(
        api.allocate_proceeds(event["id"], make_accountant_headers("acct-1"))
    )
    assert_fields(
        allocated,
        status="ALLOCATED",
        allocated_arrears_cents=1000000,
        allocated_mortgagee_cents=2500000,
        lessee_share_bps=6000,
        allocated_lessee_cents=6000000,
        allocated_lessor_cents=500000,
    )
    assert (
        allocated["allocated_arrears_cents"]
        + allocated["allocated_mortgagee_cents"]
        + allocated["allocated_lessee_cents"]
        + allocated["allocated_lessor_cents"]
    ) == 10000000
    assert allocated["allocation_detail"] == [
        {"mortgage_id": senior["id"], "amount_cents": 2000000},
        {"mortgage_id": mezz["id"], "amount_cents": 500000},
    ]

    for mortgage_id in (senior["id"], mezz["id"]):
        assert_fields(
            validate_success(api.get_mortgage(mortgage_id, admin)),
            status="EXTINGUISHED",
            outstanding_principal_cents=0,
        )
    assert fx.read_lease(api, env["lease_id"])["arrears_balance_cents"] == 0
