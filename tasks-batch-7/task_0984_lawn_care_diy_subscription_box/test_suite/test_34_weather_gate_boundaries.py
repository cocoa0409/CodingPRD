"""Weather gate threshold precision: rain >=, wind >, temp band (PRD 3.7)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_weather_gate_threshold_boundaries(api):
    """PRD 3.7: "The first is the weather gate: the platform looks up the weather advisory for the lawn's `region` on the scheduled date, and if no advisory exists for that region and date, the date is not blocked. An advisory blocks the date when its `rain_probability` is at least 0.40 (0.40 blocks, 0.39 passes, compared at two-decimal precision), when its `wind_kph` exceeds 24 (24 passes, 25 blocks), or when its `temp_high_c` is below 5 or above 32 (5 and 32 pass, 4 and 33 block). A blocked date is rejected with `ERR_WEATHER_GATE_BLOCKED` (HTTP 409)."

    Design: Corner/calculations/weather_gate_threshold_boundaries
    """
    ctx = th.setup_active_subscription(email="wg@x.com")
    box, _ = th.setup_delivered_box(ctx, lines=[th.shipment_line("FERT-01", 1)])
    sub_id = ctx["subscription"]["id"]
    headers = ctx["customer_headers"]

    advisories = [
        ("2026-06-10", dict(rain_probability=0.40)),  # >= boundary blocks
        ("2026-06-11", dict(rain_probability=0.39)),  # just under, passes
        ("2026-06-12", dict(wind_kph=25)),            # > 24 blocks
        ("2026-06-13", dict(wind_kph=24)),            # 24 passes
        ("2026-06-14", dict(temp_high_c=33)),         # above 32 blocks
        ("2026-06-15", dict(temp_high_c=32)),         # 32 passes
        ("2026-06-16", dict(temp_high_c=4)),          # below 5 blocks
        ("2026-06-17", dict(temp_high_c=5)),          # 5 passes
    ]
    for date, overrides in advisories:
        th.get_success_data(
            api.create_weather_advisory(
                th.weather_advisory_payload(region="NE-OH", date=date, **overrides),
                ADMIN,
            )
        )

    blocked_dates = ("2026-06-10", "2026-06-12", "2026-06-14", "2026-06-16")
    passing_dates = ("2026-06-11", "2026-06-13", "2026-06-15", "2026-06-17")
    for date in blocked_dates:
        th.validate_error(
            api.create_application(
                th.application_payload(sub_id, box["id"], product_sku="FERT-01",
                                       scheduled_date=date),
                headers,
            ),
            th.ApiErrorId.ERR_WEATHER_GATE_BLOCKED,
        )
    for date in passing_dates:
        task = th.validate_success(
            api.create_application(
                th.application_payload(sub_id, box["id"], product_sku="FERT-01",
                                       scheduled_date=date),
                headers,
            ),
            201,
        )
        assert task["status"] == "SCHEDULED", f"{date} must pass the gate"
