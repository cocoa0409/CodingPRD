"""Skip allowance: rolling 365-day window quota boundary (PRD 3.5)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_skip_allowance_third_succeeds_fourth_rejected(api):
    """PRD 3.5: "A skip is allowed while `skips_used_in_window` is less than 3 — so the third skip in a window succeeds and the fourth is rejected with `ERR_SKIP_ALLOWANCE_EXHAUSTED` (HTTP 422). A successful skip increments `skips_used_in_window` by 1 and flips the subscription's earliest `SCHEDULED` box — chosen by earliest `ship_date`, with ties broken by earliest `created_at` — to `SKIPPED`."

    Design: Difficulty/boundary_precision_check/skip_allowance_third_succeeds_fourth_rejected
    """
    ctx = th.setup_active_subscription(email="sk@x.com")
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]
    boxes = [
        th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                      ship_date="2026-06-01T00:00:00Z",
                      delivery_window_start="2026-06-01T00:00:00Z",
                      delivery_window_end="2026-06-10T00:00:00Z"),
        th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                      ship_date="2026-06-10T00:00:00Z",
                      delivery_window_start="2026-06-10T00:00:00Z",
                      delivery_window_end="2026-06-20T00:00:00Z"),
        th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                      ship_date="2026-06-20T00:00:00Z",
                      delivery_window_start="2026-06-20T00:00:00Z",
                      delivery_window_end="2026-06-30T00:00:00Z"),
        th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                      ship_date="2026-07-01T00:00:00Z",
                      delivery_window_start="2026-07-01T00:00:00Z",
                      delivery_window_end="2026-07-10T00:00:00Z"),
    ]

    for expected_used in (1, 2, 3):
        sub = th.validate_success(api.skip_next_shipment(sub_id, headers))
        assert sub["skips_used_in_window"] == expected_used, (
            f"skip {expected_used} must succeed (boundary value 3 is allowed)"
        )

    th.validate_error(
        api.skip_next_shipment(sub_id, headers),
        th.ApiErrorId.ERR_SKIP_ALLOWANCE_EXHAUSTED,
    )

    statuses = [
        th.validate_success(api.get_shipment(b["id"], ADMIN))["fulfillment_status"]
        for b in boxes
    ]
    assert statuses[:3] == ["SKIPPED", "SKIPPED", "SKIPPED"]
    assert statuses[3] == "SCHEDULED", "the fourth box was never selected"


def test_skip_selects_earliest_scheduled_box(api):
    """PRD 3.5: "A successful skip increments `skips_used_in_window` by 1 and flips the subscription's earliest `SCHEDULED` box — chosen by earliest `ship_date`, with ties broken by earliest `created_at` — to `SKIPPED`."

    Design: Difficulty/boundary_precision_check/skip_allowance_third_succeeds_fourth_rejected
    """
    ctx = th.setup_active_subscription(email="sk-sel@x.com")
    sub_id = ctx["subscription"]["id"]
    box_early = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                              ship_date="2026-06-01T00:00:00Z")
    box_late = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                             ship_date="2026-06-20T00:00:00Z")

    sub = th.validate_success(
        api.skip_next_shipment(sub_id, ctx["customer_headers"])
    )
    assert sub["skips_used_in_window"] == 1

    early_after = th.validate_success(api.get_shipment(box_early["id"], ADMIN))
    late_after = th.validate_success(api.get_shipment(box_late["id"], ADMIN))
    assert early_after["fulfillment_status"] == "SKIPPED", (
        "the earliest SCHEDULED box by ship_date is the one skipped"
    )
    assert late_after["fulfillment_status"] == "SCHEDULED"
