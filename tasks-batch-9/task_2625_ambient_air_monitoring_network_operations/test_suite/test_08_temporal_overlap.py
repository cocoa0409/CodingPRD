"""Half-open hour ranges and buffered event windows."""

from test_helpers import (
    ERR_EVENT_WINDOW_CONFLICT,
    ERR_INVALIDATION_RANGE_OVERLAP,
    PM_HEADERS,
    QA_HEADERS,
    apply_invalidation,
    assert_hour_budget_conserved,
    assert_pct,
    canonical_environment,
    data_batch_payload,
    demonstration_payload,
    get_success_data,
    validate_error,
    validate_success,
)


def _quarter_with_two_abutting_invalidations(api):
    env = canonical_environment(api)
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(env.monitor_id, 2025, 3, scheduled_hour_count=2160), QA_HEADERS
        )
    )
    env.batches = [batch]
    first = apply_invalidation(api, batch["id"], 0, 100, "QC_FAILURE")
    return env, batch["id"], first


def test_two_ranges_that_merely_abut_are_both_accepted(api):
    """The second range starts exactly where the first one ends.

    PRD 3.4: "Because the interval is half-open and carries no buffer, two ranges that
    merely abut — where one range's `end_hour_index` equals the next range's
    `start_hour_index` — do not intersect and are both accepted."

    Design: Difficulty/resource_temporal_overlap/invalidation_half_open_hours_allow_adjacency_reject_overlap
    """
    env, batch_id, first = _quarter_with_two_abutting_invalidations(api)

    second = validate_success(
        api.create_invalidation(
            batch_id,
            {
                "start_hour_index": 100,
                "end_hour_index": 200,
                "invalidation_code": "OPERATOR_ERROR",
                "expected_data_batch_version": get_success_data(
                    api.get_data_batch(batch_id, QA_HEADERS)
                )["version"],
            },
            QA_HEADERS,
        ),
        201,
    )
    assert second["start_hour_index"] == 100
    assert second["hours_affected"] == 100
    assert first["hours_affected"] == 100
    assert second["status"] == "APPLIED"


def test_a_range_that_intersects_an_applied_range_is_refused_and_changes_nothing(api):
    """A [150, 250) claim overlaps the applied [100, 200) hours.

    PRD 3.4: "The half-open range must also not intersect the range of any other applied
    invalidation on the same quarter; an intersection is rejected with
    `ERR_INVALIDATION_RANGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/invalidation_half_open_hours_allow_adjacency_reject_overlap
    """
    env, batch_id, _ = _quarter_with_two_abutting_invalidations(api)
    apply_invalidation(api, batch_id, 100, 200, "OPERATOR_ERROR")
    before = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))

    response = api.create_invalidation(
        batch_id,
        {
            "start_hour_index": 150,
            "end_hour_index": 250,
            "invalidation_code": "INSTRUMENT_MALFUNCTION",
            "expected_data_batch_version": before["version"],
        },
        QA_HEADERS,
    )
    validate_error(response, ERR_INVALIDATION_RANGE_OVERLAP, 409)

    after = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
    assert after["version"] == before["version"]
    assert after["invalidated_hour_count"] == 200
    assert after["valid_hour_count"] == 1960
    assert_pct(after["completeness_pct"], 90.7)
    assert_hour_budget_conserved(after)


def _draft_wildfire_claim(api):
    env = canonical_environment(api)
    demo = validate_success(
        api.create_demonstration(
            demonstration_payload(env.site_id, env.pollutant_id), PM_HEADERS
        ),
        201,
    )
    env.demonstration_id = demo["id"]
    return env


def test_the_one_day_buffer_rejects_a_claim_filed_nose_to_tail(api):
    """A window opening the day after the first one closes still collides.

    PRD 3.6: "The new claim is rejected when both of the following hold: the new
    `event_start_date` less 24 hours is at or before the other demonstration's
    `event_end_date`, and the other demonstration's `event_start_date` less 24 hours is at
    or before the new `event_end_date`."

    Design: Difficulty/resource_temporal_overlap/event_window_closed_interval_buffer_rejects_next_day_claim
    """
    env = _draft_wildfire_claim(api)

    response = api.create_demonstration(
        demonstration_payload(
            env.site_id,
            env.pollutant_id,
            event_start_date="2024-08-20T00:00:00Z",
            event_end_date="2024-08-25T00:00:00Z",
            narrative="Second smoke episode filed nose-to-tail with the first",
        ),
        PM_HEADERS,
    )
    validate_error(response, ERR_EVENT_WINDOW_CONFLICT, 409)

    accepted = validate_success(
        api.create_demonstration(
            demonstration_payload(
                env.site_id,
                env.pollutant_id,
                event_start_date="2024-08-21T00:00:00Z",
                event_end_date="2024-08-26T00:00:00Z",
                narrative="Second smoke episode clear of the one-day buffer",
            ),
            PM_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["event_start_date"].startswith("2024-08-21T00:00:00")


def test_the_conflict_test_is_partitioned_by_event_type(api):
    """A different phenomenon may claim the very window the buffer denied.

    PRD 3.6: "A new demonstration is compared against every other demonstration for the
    same `site_id` and the same `event_type` whose `status` is `DRAFT`, `SUBMITTED`,
    `INFO_REQUESTED` or `CONCURRED`"

    Design: Difficulty/resource_temporal_overlap/event_window_closed_interval_buffer_rejects_next_day_claim
    """
    env = _draft_wildfire_claim(api)

    other_type = validate_success(
        api.create_demonstration(
            demonstration_payload(
                env.site_id,
                env.pollutant_id,
                event_type="HIGH_WIND_DUST",
                event_start_date="2024-08-20T00:00:00Z",
                event_end_date="2024-08-25T00:00:00Z",
                narrative="Blowing dust episode over the same site",
            ),
            PM_HEADERS,
        ),
        201,
    )
    assert other_type["status"] == "DRAFT"
    assert other_type["event_type"] == "HIGH_WIND_DUST"
    assert other_type["info_request_count"] == 0

    first = get_success_data(api.get_demonstration(env.demonstration_id, PM_HEADERS))
    assert first["status"] == "DRAFT"
    assert first["excluded_hour_total"] == 0
