"""Cross-cutting layers: optimistic concurrency, revision counters and QC runs.

These tests replay stale expectations, watch a parent revision counter move on a
child write, and drive a failure run through the quality-control grading bands.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    EPA_HEADERS,
    PM_HEADERS,
    QA_HEADERS,
    TECH_HEADERS,
    ERR_STALE_BATCH_VERSION,
    ERR_STALE_SITE_VERSION,
    assert_hour_budget_conserved,
    assert_pct,
    canonical_environment,
    data_batch_payload,
    design_value_payload,
    find_by_id,
    get_success_data,
    invalidation_payload,
    monitor_payload,
    network_payload,
    pollutant_payload,
    reference_method_payload,
    set_clock,
    site_payload,
    span_check_payload,
    twelve_validated_quarters,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-01-05T00:00:00Z"


def assert_instant(actual, expected):
    """Compare a server instant against an expected UTC instant."""
    assert type(actual) is str, f"expected an instant string, got {actual!r}"
    assert actual.endswith("Z"), f"expected a UTC instant, got {actual!r}"
    assert actual[:19] == expected[:19], f"expected {expected}, got {actual}"


def test_a_stale_expected_data_batch_version_is_rejected(api):
    """A replayed quarter revision is refused; the re-read revision succeeds.

    PRD 2.7: "Its value must equal the target quarter's current `version` at the moment the request is processed; if it does not, the request is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412)."
    PRD 2.7: "On success the quarter's `version` increments, which in turn invalidates any other client's stale expectation."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_data_batch_version_is_rejected
    """
    env = canonical_environment(api)
    batch = validate_success(
        api.create_data_batch(data_batch_payload(env.monitor_id, 2025, 1), QA_HEADERS), 201
    )
    version_before = batch["version"]
    validate_success(
        api.create_invalidation(
            batch["id"],
            invalidation_payload(0, 100, "QC_FAILURE", version_before),
            QA_HEADERS,
        ),
        201,
    )

    validate_error(
        api.create_invalidation(
            batch["id"],
            invalidation_payload(200, 300, "OPERATOR_ERROR", version_before),
            QA_HEADERS,
        ),
        ERR_STALE_BATCH_VERSION,
        412,
    )
    _, meta = validate_paginated(api.list_batch_invalidations(batch["id"], QA_HEADERS))
    assert meta["total_count"] == 1, "the refused call must not have persisted an invalidation"

    current = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert current["version"] == version_before + 1

    second = validate_success(
        api.create_invalidation(
            batch["id"],
            invalidation_payload(200, 300, "OPERATOR_ERROR", current["version"]),
            QA_HEADERS,
        ),
        201,
    )
    assert second["hours_affected"] == 100
    assert second["status"] == "APPLIED"

    settled = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert settled["invalidated_hour_count"] == 200
    assert settled["valid_hour_count"] == 1960
    assert_pct(settled["completeness_pct"], 90.7)
    assert_hour_budget_conserved(settled)


def test_a_stale_expected_monitoring_site_version_is_rejected(api):
    """A second determination replaying the pre-computation site revision fails.

    PRD 2.7: "Its value must equal the referenced site's current `version`; a mismatch is rejected with `ERR_STALE_SITE_VERSION` (HTTP 412)."
    PRD 2.7: "A successful computation increments the site's `version`."
    PRD 3.7: "Any earlier design value for the same site, pollutant, `period_end_year` and `variant` that was still `PROVISIONAL` moves to `SUPERSEDED` with `stale_reason` set to `RECOMPUTED` and its `version` incremented; the referenced site's `version` increments by 1 and its `current_attainment_status` is refreshed."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_monitoring_site_version_is_rejected
    """
    env = twelve_validated_quarters(api)
    version_before = env.site_version()

    first = validate_success(
        api.create_design_value(
            design_value_payload(
                env.site_id, env.pollutant_id, 2025, "WITH_EVENT_DATA", version_before
            ),
            PM_HEADERS,
        ),
        201,
    )
    assert first["status"] == "PROVISIONAL"

    validate_error(
        api.create_design_value(
            design_value_payload(
                env.site_id, env.pollutant_id, 2025, "WITH_EVENT_DATA", version_before
            ),
            PM_HEADERS,
        ),
        ERR_STALE_SITE_VERSION,
        412,
    )

    version_after = env.site_version()
    assert version_after == version_before + 1

    second = validate_success(
        api.create_design_value(
            design_value_payload(
                env.site_id, env.pollutant_id, 2025, "WITH_EVENT_DATA", version_after
            ),
            PM_HEADERS,
        ),
        201,
    )
    assert second["status"] == "PROVISIONAL"
    assert second["design_value"] == pytest.approx(9.1, abs=0.01)

    superseded = get_success_data(api.get_design_value(first["id"], PM_HEADERS))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["stale_reason"] == "RECOMPUTED"

    rows, meta = validate_paginated(
        api.list_design_values(PM_HEADERS, {"site_id": env.site_id, "status": "PROVISIONAL"})
    )
    assert meta["total_count"] == 1
    assert find_by_id(rows, second["id"]) is not None


def test_the_site_version_increments_on_every_write_that_touches_it(api):
    """The site revision counter moves on its own writes and on a child write.

    PRD 2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."
    PRD 2.4: "The `version` counter is what makes optimistic concurrency possible (§2.7) and what makes cascades observable: when an operation on one resource mutates a second resource, the second resource's `version` increments and its `updated_at` is refreshed too, even though the client never named it."
    PRD 3.2: "The network's `approved_site_count` decrements by 1 and `operating_site_count` increments by 1, and both rows' `version` counters increment."
    PRD 3.3: "On success the site's `operating_monitor_count` increments by 1, both the instrument's and the site's `version` increment, and the instrument becomes visible to the primary-monitor selector described in §3.7."

    Design: Corner/cross_cutting_complexity_layers/the_site_version_increments_on_every_write_that_touches_it
    """
    set_clock(api, CLOCK)
    pollutant = validate_success(api.create_pollutant(pollutant_payload(), ADMIN_HEADERS), 201)
    method = validate_success(
        api.create_reference_method(reference_method_payload(pollutant["id"]), ADMIN_HEADERS), 201
    )
    network = validate_success(api.create_network(network_payload(), ADMIN_HEADERS), 201)

    created = validate_success(api.create_site(site_payload(network["id"]), ADMIN_HEADERS), 201)
    version_created = created["version"]
    assert version_created == 1

    version_siting = validate_success(
        api.approve_siting(created["id"], {"waiver_granted": False}, EPA_HEADERS), 200
    )["version"]
    assert version_siting == version_created + 1

    version_operating = validate_success(
        api.commence_operations(created["id"], {}, PM_HEADERS), 200
    )["version"]
    assert version_operating == version_siting + 1

    monitor = validate_success(
        api.create_monitor(
            monitor_payload(created["id"], method["id"], installed_at="2026-01-01T00:00:00Z"),
            ADMIN_HEADERS,
        ),
        201,
    )
    validate_success(api.approve_monitor(monitor["id"], {}, EPA_HEADERS), 200)
    validate_success(api.commission_monitor(monitor["id"], {}, TECH_HEADERS), 200)

    after_commission = validate_success(api.get_site(created["id"], PM_HEADERS), 200)
    assert after_commission["version"] == version_operating + 1
    assert after_commission["operating_monitor_count"] == 1

    read_again = validate_success(api.get_site(created["id"], PM_HEADERS), 200)
    assert read_again["version"] == after_commission["version"], "a read must not bump the counter"


def test_the_consecutive_failure_counter_accumulates_and_resets(api):
    """Two failing span checks accumulate the run and one pass clears it.

    The two drift readings sit beyond one and a half times the tolerance, so
    both grade as failures, and the third reading is well inside the tolerance.

    PRD 3.3: "Second, `consecutive_qc_failure_count` increments by 1 on a `FAIL` and resets to 0 on a `PASS` or a `WARN`; it counts the run of failures since the last non-failing event."
    PRD 3.3: "For a span check, take the absolute value of `span_drift_pct`, round it to two decimal places, and compare it against the governing method's `max_span_drift_pct`: an absolute drift at or below the tolerance is `PASS`, a drift above the tolerance but at or below one and a half times the tolerance is `WARN`, and anything beyond that is `FAIL`."
    PRD 3.3: "Third, an instrument that is `OPERATING` when it records a `FAIL` is automatically driven `OPERATING → OUT_OF_SERVICE` in the same request, with `out_of_service_since` stamped from the logical clock and the site's `operating_monitor_count` decremented — the instrument is pulled from service without anyone asking."

    Design: Corner/cross_cutting_complexity_layers/the_consecutive_failure_counter_accumulates_and_resets
    """
    env = canonical_environment(api)

    first_failure = validate_success(
        api.create_qc_event(
            env.monitor_id,
            span_check_payload(performed_at="2026-01-03T00:00:00Z", span_drift_pct=8.0),
            TECH_HEADERS,
        ),
        201,
    )
    assert first_failure["outcome"] == "FAIL"
    after_first = env.read_monitor()
    assert after_first["consecutive_qc_failure_count"] == 1
    assert after_first["monitor_status"] == "OUT_OF_SERVICE"
    assert_instant(after_first["out_of_service_since"], CLOCK)
    assert_instant(after_first["last_span_check_at"], "2026-01-02T00:00:00Z")

    second_failure = validate_success(
        api.create_qc_event(
            env.monitor_id,
            span_check_payload(performed_at="2026-01-04T00:00:00Z", span_drift_pct=9.0),
            TECH_HEADERS,
        ),
        201,
    )
    assert second_failure["outcome"] == "FAIL"
    after_second = env.read_monitor()
    assert after_second["consecutive_qc_failure_count"] == 2
    assert after_second["monitor_status"] == "OUT_OF_SERVICE"
    assert_instant(after_second["last_span_check_at"], "2026-01-02T00:00:00Z")

    passing = validate_success(
        api.create_qc_event(
            env.monitor_id,
            span_check_payload(performed_at="2026-01-05T00:00:00Z", span_drift_pct=1.0),
            TECH_HEADERS,
        ),
        201,
    )
    assert passing["outcome"] == "PASS"
    after_pass = env.read_monitor()
    assert after_pass["consecutive_qc_failure_count"] == 0
    assert_instant(after_pass["last_span_check_at"], "2026-01-05T00:00:00Z")
    assert after_pass["monitor_status"] == "OUT_OF_SERVICE"
