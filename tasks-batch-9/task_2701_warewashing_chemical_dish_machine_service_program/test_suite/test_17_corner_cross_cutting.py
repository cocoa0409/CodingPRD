"""
Layered rules: optimistic concurrency on top of pricing and measurement, and a
cumulative alert threshold on top of the counter a verified visit resets.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_STALE_PARENT_VERSION
from test_helpers.assertions import assert_axes, assert_cents, assert_pct
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
)
from test_helpers.types import (
    ALERT_CALIBRATION_OVERDUE,
    OP_DEGRADED,
    OP_UP,
    SEVERITY_WARNING,
    VERDICT_PASS,
    VISIT_VERIFIED,
)


def test_a_replayed_site_token_refuses_the_second_drop_without_pricing_it(api):
    """
    Two drops of the same product to the same kitchen are both legitimate, so nothing
    but the token can refuse the second: replaying the version observed before the first
    drop is refused as stale, no row is written and the version does not move again. The
    identical payload with the refreshed token is accepted and prices exactly as it
    would have, so the site version advances by precisely one per accepted write.

    PRD §2.7: "A `POST /warewashing/chemical-deliveries` request must carry
    `expected_site_version`, a non-optional field holding the client's last observed
    `version` of the target `Site`. If it does not equal the site's current `version`,
    the create is rejected with `ERR_STALE_PARENT_VERSION` and HTTP 412, because the
    delivery was priced against an out-of-date view of the site's inventory ledger."

    Design: Corner/cross_cutting_complexity_layers/a_stale_site_version_rejects_the_delivery_without_pricing_it
    """
    base = X.program_base(api)
    stale_token = X.site_version(api, base["site_id"])

    first = validate_success(
        api.create_chemical_delivery(
            F.chemical_delivery_payload(
                base["site_id"],
                base["detergent_id"],
                stale_token,
                unit_count=10,
                delivered_at="2026-08-02T00:00:00Z",
            ),
            ACCOUNT_MANAGER_HEADERS,
        ),
        201,
    )
    # 10 units earn the 5 percent tier: 9600 x 0.95 = 9120 per container.
    assert_cents(first["amount_cents"], 91200)

    bulk = F.chemical_delivery_payload(
        base["site_id"],
        base["detergent_id"],
        stale_token,
        unit_count=25,
        delivered_at="2026-08-03T00:00:00Z",
    )
    validate_error(
        api.create_chemical_delivery(bulk, ACCOUNT_MANAGER_HEADERS),
        ERR_STALE_PARENT_VERSION,
        412,
    )

    fresh_token = X.site_version(api, base["site_id"])
    assert fresh_token == stale_token + 1

    bulk["expected_site_version"] = fresh_token
    second = validate_success(
        api.create_chemical_delivery(bulk, ACCOUNT_MANAGER_HEADERS), 201
    )
    # 25 units earn the 12 percent tier: 9600 x 0.88 = 8448 per container.
    assert_cents(second["amount_cents"], 211200)

    _, meta = validate_paginated(
        api.list_chemical_deliveries(
            ACCOUNT_MANAGER_HEADERS, {"site_id": base["site_id"]}
        )
    )
    assert meta["total_count"] == 2


def test_a_replayed_feed_token_refuses_the_superseding_measurement(api):
    """
    A second measurement of the same feed inside the same visit is legitimate — it is how
    a first reading is superseded — so only the token can refuse it. The first record
    bumps the feed's version even though nothing was applied, so replaying the original
    token is refused as stale while the refreshed token is accepted, stamps its own
    drift, and takes the visit's record count to two.

    PRD §2.7: "A `POST /warewashing/service-visits/{visit_id}/calibration-records`
    request must carry `expected_dispenser_version`, a non-optional field holding the
    client's last observed `version` of the target `Dispenser`. If it does not equal the
    dispenser's current `version`, the create is rejected with
    `ERR_STALE_PARENT_VERSION` and HTTP 412, because the technician measured against a
    dose that has since been superseded."

    PRD §3.6: "Every record stores `visit_id`, `recorded_by_user_id` from the engineer's
    `X-User-ID`, and `applied` false."

    Design: Corner/cross_cutting_complexity_layers/a_stale_dispenser_version_rejects_the_second_calibration_record
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C01")
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)
    work = X.visit_in_progress(api, base, placement["id"])

    stale_token = X.dispenser_version(
        api, dispenser["id"], base["technician_id"]
    )
    first = validate_success(
        api.create_calibration_record(
            work["visit_id"],
            F.calibration_record_payload(dispenser["id"], 1200, 8.00, stale_token),
            base["technician_headers"],
        ),
        201,
    )
    assert first["applied"] is False

    fresh_token = X.dispenser_version(api, dispenser["id"], base["technician_id"])
    assert fresh_token == stale_token + 1

    superseding = F.calibration_record_payload(
        dispenser["id"], 1260, 8.00, stale_token
    )
    validate_error(
        api.create_calibration_record(
            work["visit_id"], superseding, base["technician_headers"]
        ),
        ERR_STALE_PARENT_VERSION,
        412,
    )

    superseding["expected_dispenser_version"] = fresh_token
    second = validate_success(
        api.create_calibration_record(
            work["visit_id"], superseding, base["technician_headers"]
        ),
        201,
    )
    assert_pct(second["drift_pct"], 5.00)

    visit = get_success_data(
        api.get_service_visit(work["visit_id"], base["technician_headers"])
    )
    assert visit["calibration_record_count"] == 2


def test_the_overdue_threshold_counts_from_the_last_applied_calibration(api):
    """
    The overdue trigger is cumulative, so it needs both a boundary and a reset: one cycle
    short of the model's limit raises nothing, the cycle that reaches it opens the warning
    and degrades the machine, and a verified visit both resets the since-calibration
    counter and resolves the warning. A further sample afterwards raises nothing at all,
    even though the lifetime odometer is well past the limit — an implementation reading
    the lifetime count instead of the since-calibration count re-fires here.

    PRD §3.4: "`CALIBRATION_OVERDUE` fires when the placement's
    `cycles_since_calibration`, evaluated **after** this reading has been applied, has
    reached or passed the model's `max_cycles_between_calibrations`, with `severity`
    `WARNING`, and only when this placement has no `CALIBRATION_OVERDUE` alert already
    standing in `OPEN` or `ACKNOWLEDGED`."

    PRD §3.4: "Ingest also refreshes the placement's `last_cycle_count` to the newest
    `DEVICE` reading's `cycle_count_total` and updates `cycles_since_calibration`, which
    is `last_cycle_count` minus the `last_cycle_count` that stood when the placement's
    most recent calibration was applied."

    PRD §3.6: "When the verified visit also carried `repair_confirmed` true, the
    machine's health is reassessed. Every alert of the placement standing in `OPEN` or
    `ACKNOWLEDGED` becomes `RESOLVED` and `open_alert_count` returns to 0, and only
    **then** is `operational_status` re-derived: a placement that was `DOWN` or
    `DEGRADED` becomes `UP` when no alert remains in `OPEN` or `ACKNOWLEDGED` and no
    dispenser of the placement remains `LOCKED_OUT`, and becomes — or stays —
    `DEGRADED` when at least one alert remains open or at least one dispenser remains
    locked out."

    Design: Corner/cross_cutting_complexity_layers/an_applied_calibration_restarts_the_cycle_threshold
    """
    base = X.program_base(api)
    placement = X.installed_placement(
        api, base, asset_tag="AT-C01", initial_cycle_count=0
    )
    dispenser = X.fit_dispenser(api, base, placement["id"], dose=8.00)

    one_short = X.ingest_reading(
        api, placement["id"], "2026-08-01T00:00:00Z", 19999
    )
    assert one_short["cycle_delta"] == 19999
    before = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert before["cycles_since_calibration"] == 19999
    assert before["open_alert_count"] == 0
    assert_axes(before, operational_status=OP_UP)

    X.set_clock(api, "2026-08-01T01:00:00Z")
    X.ingest_reading(api, placement["id"], "2026-08-01T01:00:00Z", 20000)
    at_threshold = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert at_threshold["cycles_since_calibration"] == 20000
    assert at_threshold["open_alert_count"] == 1
    assert_axes(at_threshold, operational_status=OP_DEGRADED)

    alerts, alert_meta = validate_paginated(
        api.list_telemetry_alerts(
            base["technician_headers"],
            {
                "placement_id": placement["id"],
                "alert_type": ALERT_CALIBRATION_OVERDUE,
            },
        )
    )
    assert alert_meta["total_count"] == 1
    assert alerts[0]["severity"] == SEVERITY_WARNING

    ticket = X.file_ticket(api, base, placement["id"])
    X.dispatch_ticket(api, ticket["id"])
    visit = X.book_visit(
        api,
        base,
        ticket["id"],
        scheduled_start_at="2026-08-01T11:00:00Z",
        scheduled_end_at="2026-08-01T12:00:00Z",
    )
    X.set_clock(api, "2026-08-01T11:00:00Z")
    X.arrive_visit(api, base, visit["id"])
    record = X.record_calibration(
        api, base, visit["id"], dispenser["id"], measured_ppm=1200
    )
    assert record["calibration_verdict"] == VERDICT_PASS

    X.submit_visit(api, base, visit["id"], repair_confirmed=True)
    verified = X.verify_visit(api, visit["id"], auditor_headers=AUDITOR_1_HEADERS)
    assert verified["visit_status"] == VISIT_VERIFIED

    after_service = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert after_service["cycles_since_calibration"] == 0
    assert after_service["open_alert_count"] == 0
    assert_axes(after_service, operational_status=OP_UP)

    X.set_clock(api, "2026-08-01T14:00:00Z")
    X.ingest_reading(api, placement["id"], "2026-08-01T14:00:00Z", 20001)
    afterwards = get_success_data(
        api.get_machine_placement(placement["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert afterwards["cycles_since_calibration"] == 1
    assert afterwards["last_cycle_count"] == 20001
    assert afterwards["open_alert_count"] == 0
    assert_axes(afterwards, operational_status=OP_UP)
