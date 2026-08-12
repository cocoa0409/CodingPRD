"""Category buffer: minimum-clearance gap on the same lawn (PRD 3.7)."""
import test_helpers as th


def _setup_fert_task(api, email, seed_skus=("FERT-01", "WEED-01"),
                     box_lines=None, fert_date="2026-06-10"):
    """Delivered box and one SCHEDULED FERT-01 task on fert_date."""
    if box_lines is None:
        box_lines = [th.shipment_line("FERT-01", 1), th.shipment_line("WEED-01", 1)]
    ctx = th.setup_active_subscription(
        email=email,
        plan_lines=[th.plan_line("FERT-01", qty_units=1, target_month=6)],
        seed_skus=seed_skus,
    )
    box, _ = th.setup_delivered_box(ctx, lines=box_lines)
    task = th.validate_success(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date=fert_date),
            ctx["customer_headers"],
        ),
        201,
    )
    return ctx, box, task


def test_buffer_gap_ten_days_fails_fourteen_days_passes(api):
    """PRD 3.7: "for any existing application task of the same lawn in `SCHEDULED`, `FROZEN`, or `APPLIED` whose product category conflicts with the new product's category — conflict in either direction of `conflicting_categories` counts — the absolute difference in days between the new date and the existing task's date must be at least the new product's `min_gap_days`. A gap exactly equal to `min_gap_days` passes; a gap one day shorter fails with `ERR_APPLICATION_BUFFER_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/application_buffer_gap_on_lawn
    """
    ctx, box, _ = _setup_fert_task(api, email="buf@x.com")
    sub_id = ctx["subscription"]["id"]

    # 2026-06-20 is 10 days from the FERT-01 task: inside the 14-day clearance.
    th.validate_error(
        api.create_application(
            th.application_payload(sub_id, box["id"], product_sku="WEED-01",
                                   scheduled_date="2026-06-20"),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_APPLICATION_BUFFER_CONFLICT,
    )

    # 2026-06-24 is exactly 14 days away: the >= boundary passes.
    task2 = th.validate_success(
        api.create_application(
            th.application_payload(sub_id, box["id"], product_sku="WEED-01",
                                   scheduled_date="2026-06-24"),
            ctx["customer_headers"],
        ),
        201,
    )
    assert task2["status"] == "SCHEDULED"


def test_buffer_gap_thirteen_days_fails_and_non_conflicting_category_passes(api):
    """PRD 3.7: "With the default gap of 14 days, a conflicting application two weeks to the day away is acceptable, while thirteen days away is not."
    PRD 3.7: "for any existing application task of the same lawn in `SCHEDULED`, `FROZEN`, or `APPLIED` whose product category conflicts with the new product's category — conflict in either direction of `conflicting_categories` counts — the absolute difference in days between the new date and the existing task's date must be at least the new product's `min_gap_days`."

    Design: Difficulty/resource_temporal_overlap/application_buffer_gap_on_lawn
    """
    ctx, box, _ = _setup_fert_task(
        api,
        email="buf13@x.com",
        seed_skus=("FERT-01", "WEED-01", "SEED-A"),
        box_lines=[th.shipment_line("FERT-01", 1), th.shipment_line("WEED-01", 1),
                   th.shipment_line("SEED-A", 1)],
    )
    sub_id = ctx["subscription"]["id"]

    # 13 days from the FERT-01 task: one day short of the default 14-day gap.
    th.validate_error(
        api.create_application(
            th.application_payload(sub_id, box["id"], product_sku="WEED-01",
                                   scheduled_date="2026-06-23"),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_APPLICATION_BUFFER_CONFLICT,
    )

    # SEED-A declares no conflicting categories and FERT-01 does not conflict
    # with SEED either — one day of separation is fine.
    task2 = th.validate_success(
        api.create_application(
            th.application_payload(sub_id, box["id"], product_sku="SEED-A",
                                   scheduled_date="2026-06-11"),
            ctx["customer_headers"],
        ),
        201,
    )
    assert task2["status"] == "SCHEDULED"
