"""Site storage billing: the marginal day bands, the partial-day ceiling, the
insurance cap arm, and the discount tier pinned to the pre-discount total."""

from test_helpers import (
    COMPLIANCE_OFFICER,
    LOGISTICS_COORDINATOR,
    USER_COMPLIANCE_1,
    USER_QUALITY_1,
    assert_order_state,
    assert_storage_fee_breakdown,
    create_bay,
    create_component,
    create_order,
    create_release,
    create_supplier,
    drive_order_to_in_production,
    issue_label,
    read_order,
    run_fat_to_conclusion,
    set_clock,
    site_storage_agreement_payload,
)
from prd_bench_local_runner.testing import validate_success


def test_three_storage_episodes_pin_every_band_edge_of_the_fee_waterfall(api):
    """PRD 3.7: "The exact elapsed hours between `storage_start_at` and
    `storage_end_at` are divided by 24 and rounded **up** to a whole number of
    days... The first band is the lesser of `billable_days` and 30 days, charged at
    1200 cents per crate per day. The second band covers days 31 through 90...
    charged at 900 cents per crate per day. The third band covers day 91 onward...
    charged at 700 cents per crate per day"; and "the long-stay discount, whose
    tier is selected from that pre-discount grand total... A pre-discount total of
    500000 cents or more but below 2000000 cents earns 300 basis points."

    Design: Difficulty/boundary_precision_check/site_storage_marginal_bands_partial_day_ceiling_and_pre_discount_tier_pinning
    """
    set_clock(api, "2026-01-05T00:00:00Z")
    order = create_order(
        api,
        order_number="TX-BND-0013",
        customer_name="Seabright Terminal",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=4000000,
        sold_at="2026-01-05T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    supplier = create_supplier(
        api, supplier_code="SUP-B13", legal_name="Seabright Cores", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="CORE-B13",
        category="CORE_STEEL_COIL",
        lead_time_days=30,
        quantity_on_hand=4,
        allocation_policy="PROTECTED",
    )
    material = drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=2,
        need_by_date="2026-07-01T00:00:00Z",
        drawing_set_code="DS-B13",
    )
    bay = create_bay(
        api, bay_code="BAY-B13", max_kv=145, changeover_buffer_hours=4,
        supports_impulse=True,
    )
    outcome = run_fat_to_conclusion(
        api,
        order["id"],
        bay["id"],
        "2026-02-10T08:00:00Z",
        "2026-02-10T09:00:00Z",
        result="PASS",
        report_overrides={
            "winding_temp_rise_c": 50,
            "temp_rise_limit_c": 65,
            "short_circuit_current_ka": 20,
            "arc_duration_ms": 150,
            "working_distance_mm": 455,
        },
    )
    label = issue_label(
        api,
        order["id"],
        material["drawing"]["id"],
        outcome["report"]["id"],
        generated_by_user_id=USER_COMPLIANCE_1,
        verified_by_user_id=USER_QUALITY_1,
    )
    assert label["status"] == "ISSUED"
    release = create_release(api, order["id"])
    validate_success(
        api.clear_shipment_release(release["id"], {}, LOGISTICS_COORDINATOR)
    )
    set_clock(api, "2026-02-20T00:00:00Z")
    staged = validate_success(
        api.stage_shipment_release(release["id"], {}, LOGISTICS_COORDINATOR)
    )
    assert staged["status"] == "STAGED"
    assert staged["storage_fee_accrued_cents"] == 0

    def open_agreement(storage_start_at, storage_end_at, crate_count, insured):
        agreement = validate_success(
            api.create_site_storage_agreement(
                release["id"],
                site_storage_agreement_payload(
                    storage_start_at=storage_start_at,
                    storage_end_at=storage_end_at,
                    crate_count=crate_count,
                    insured_value_cents=insured,
                ),
                LOGISTICS_COORDINATOR,
            ),
            201,
        )
        assert agreement["status"] == "OPEN"
        parked = validate_success(
            api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
        )
        assert parked["status"] == "SITE_STORAGE"
        return agreement

    def close_agreement(agreement, clock_at, storage_end_at):
        set_clock(api, clock_at)
        closed = validate_success(
            api.close_site_storage_agreement(
                agreement["id"],
                {"storage_end_at": storage_end_at},
                LOGISTICS_COORDINATOR,
            )
        )
        assert closed["status"] == "CLOSED"
        assert validate_success(
            api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
        )["status"] == "STAGED"
        return closed

    # Episode one: exactly 720 hours, so the ceiling has nothing to round and
    # every day sits inside the first band.
    ssa_1 = open_agreement("2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z", 1, 0)
    closed_1 = close_agreement(ssa_1, "2026-03-31T01:00:00Z", "2026-03-31T00:00:00Z")
    assert_storage_fee_breakdown(
        closed_1,
        billable_days=30,
        storage_subtotal_cents=36000,
        insurance_surcharge_cents=0,
        long_stay_discount_cents=0,
        total_fee_cents=36000,
    )

    # Episode two: one hour more crosses into a 31st billable day, and that day
    # is charged at the second band's 900, not the first band's 1200. The
    # insurance surcharge is decided by the 25%-of-subtotal cap, not the 3 bp
    # rate on a very large insured value.
    ssa_2 = open_agreement("2026-04-01T00:00:00Z", "2026-05-01T01:00:00Z", 4, 600000000)
    closed_2 = close_agreement(ssa_2, "2026-05-01T02:00:00Z", "2026-05-01T01:00:00Z")
    assert_storage_fee_breakdown(
        closed_2,
        billable_days=31,
        storage_subtotal_cents=147600,
        insurance_surcharge_cents=36900,
        long_stay_discount_cents=0,
        total_fee_cents=184500,
    )

    # Episode three: 100 days reaches the third band, and the pre-discount total
    # lands exactly on the tier threshold. Equality discounts at 300 bp, and the
    # tier is not re-derived from the discounted total.
    ssa_3 = open_agreement("2026-05-02T00:00:00Z", "2026-08-10T00:00:00Z", 5, 50000000)
    closed_3 = close_agreement(ssa_3, "2026-08-10T01:00:00Z", "2026-08-10T00:00:00Z")
    assert_storage_fee_breakdown(
        closed_3,
        billable_days=100,
        storage_subtotal_cents=485000,
        insurance_surcharge_cents=15000,
        long_stay_discount_cents=15000,
        total_fee_cents=485000,
    )

    # The stage accumulates across every episode.
    final_release = validate_success(
        api.get_shipment_release(release["id"], LOGISTICS_COORDINATOR)
    )
    assert final_release["status"] == "STAGED"
    assert final_release["storage_fee_accrued_cents"] == 705500

    # SITE_NOT_READY is collected only while an agreement is OPEN.
    assert_order_state(
        read_order(api, order["id"]),
        fulfillment_status="FAT_COMPLETE",
        production_posture="OPEN",
        posture_reason_codes=[],
    )
    assert validate_success(
        api.get_compliance_label(label["id"], COMPLIANCE_OFFICER)
    )["status"] == "ISSUED"
