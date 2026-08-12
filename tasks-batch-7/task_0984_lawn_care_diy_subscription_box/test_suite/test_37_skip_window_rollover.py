"""Skip allowance rolling-window rollover and reset (PRD 3.5)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_skip_window_rollover_resets_counter(api):
    """PRD 3.5: "The allowance works on a rolling 365-day window: if `skip_window_anchor` is null, or the current logical time has reached or passed the anchor plus 365 days, the counter `skips_used_in_window` resets to 0 and re-anchors at this skip's timestamp."

    Design: Corner/calculations/skip_window_rollover_resets_counter
    """
    ctx = th.setup_active_subscription(email="sr@x.com")
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]
    box4 = None
    for start, end in (
        ("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z"),
        ("2026-06-10T00:00:00Z", "2026-06-20T00:00:00Z"),
        ("2026-06-20T00:00:00Z", "2026-06-30T00:00:00Z"),
        ("2026-07-01T00:00:00Z", "2026-07-10T00:00:00Z"),
    ):
        box = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                            ship_date=start, delivery_window_start=start,
                            delivery_window_end=end)
        box4 = box  # keep the last one

    # Three skips consumed in the first window (anchor 2026-05-01, the
    # default logical time).
    for _ in range(3):
        th.validate_success(api.skip_next_shipment(sub_id, headers))
    sub = th.validate_success(api.get_subscription(sub_id, ADMIN))
    assert sub["skips_used_in_window"] == 3

    # 2027-05-02 has reached anchor (2026-05-01) + 365 days: reset.
    th.set_clock("2027-05-02T00:00:00Z")
    sub = th.validate_success(api.skip_next_shipment(sub_id, headers))
    assert sub["skips_used_in_window"] == 1, (
        "the counter reset and re-anchored at this skip's timestamp"
    )
    box4_after = th.validate_success(api.get_shipment(box4["id"], ADMIN))
    assert box4_after["fulfillment_status"] == "SKIPPED"
