"""Application reminder computed read tracks the weather gate (PRD 3.7)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_reminder_reflects_weather_gate(api):
    """PRD 3.7: "A computed read answers whether an application reminder should fire for a task's `scheduled_date`, given the weather gate and the product window. It returns `reminder_recommended` as a boolean and `blocking_reasons` as a list of the reasons that currently block the date, if any."
    PRD 3.7: "The first is the weather gate: the platform looks up the weather advisory for the lawn's `region` on the scheduled date, and if no advisory exists for that region and date, the date is not blocked."

    Design: Corner/endpoints/reminder_reflects_weather_gate
    """
    ctx = th.setup_active_subscription(email="e1@x.com")
    box, _ = th.setup_delivered_box(ctx, lines=[th.shipment_line("FERT-01", 1)])
    task = th.validate_success(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-06-10"),
            ctx["customer_headers"],
        ),
        201,
    )

    # No advisory on file for (NE-OH, 2026-06-10): the date is not blocked.
    reminder = th.validate_success(
        api.get_application_reminder(task["id"], ctx["customer_headers"])
    )
    assert reminder["reminder_recommended"] is True

    # A blocking advisory (rain 0.90 >= 0.40) flips the recommendation.
    th.get_success_data(
        api.create_weather_advisory(
            th.weather_advisory_payload(region="NE-OH", date="2026-06-10",
                                        rain_probability=0.90),
            ADMIN,
        )
    )
    reminder = th.validate_success(
        api.get_application_reminder(task["id"], ctx["customer_headers"])
    )
    assert reminder["reminder_recommended"] is False
    assert isinstance(reminder["blocking_reasons"], list)
    assert len(reminder["blocking_reasons"]) > 0
