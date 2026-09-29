"""Rejection behaviour: uniqueness keys, range and window bounds, conditional
field requirements, readiness gates and cross-row state guards.

Each test drives one refusal through HTTP, checks the exact error identifier
and status the PRD names for it, and then proves the rejected write left no
trace. Companion legs assert the neighbouring accepted case wherever the PRD
makes the boundary explicit. The harness restarts the API server before each
test, so each test builds the whole world it needs.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    EPA_HEADERS,
    PM2_HEADERS,
    PM_HEADERS,
    QA2_HEADERS,
    QA_HEADERS,
    WORKED_EXAMPLE_QUARTERS,
    ERR_BATCH_CERTIFIED,
    ERR_BATCH_PERIOD_NOT_ENDED,
    ERR_DESIGN_VALUE_FINALIZED,
    ERR_DESIGN_VALUE_INCOMPLETE,
    ERR_DUPLICATE_BATCH_PERIOD,
    ERR_DUPLICATE_MONITOR_POC,
    ERR_DUPLICATE_SITE_CODE,
    ERR_EVENT_WINDOW_OUTSIDE_BATCH_PERIOD,
    ERR_EXCLUSION_OVERLAPS_INVALIDATION,
    ERR_INVALID_STATE,
    ERR_INVALIDATION_RANGE_OUT_OF_BOUNDS,
    ERR_NO_ELIGIBLE_BATCHES,
    ERR_PACKAGE_NOT_READY,
    ERR_PRIMARY_MONITOR_MISSING,
    ERR_REPLACEMENT_SITE_NOT_ELIGIBLE,
    ERR_REPLACEMENT_SITE_REQUIRED,
    ERR_SITE_NOT_OPERATING,
    ERR_SITING_CRITERIA_NOT_MET,
    apply_invalidation,
    approve_monitor,
    approve_siting,
    approved_assessment,
    assert_pct,
    assert_siting_codes,
    assessment_payload,
    batch_version,
    canonical_environment,
    change_request_payload,
    compute_design_value,
    create_network,
    create_reference_method,
    data_batch_payload,
    demonstration_payload,
    design_value_payload,
    exclusion_payload,
    get_success_data,
    invalidation_payload,
    monitor_payload,
    open_package,
    site_payload,
    twelve_validated_quarters,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_duplicate_site_code_inside_one_network_is_rejected(api, site_env):
    """A site code already taken inside the same network is refused, and the
    network's census does not grow.

    PRD 3.2: "The administrator supplies `network_id`, a `site_code` between 1 and 20 characters that must be unique within that network across sites in *any* status — a collision, including with a site long since shut down, is rejected with `ERR_DUPLICATE_SITE_CODE` (HTTP 409) — and a `site_type` naming the siting objective class: `POPULATION_ORIENTED`, `SOURCE_ORIENTED`, `BACKGROUND` or `TRANSPORT`."

    Design: Corner/validations/duplicate_site_code_inside_the_same_network_is_rejected
    """
    response = api.create_site(
        site_payload(
            site_env.network_id,
            site_code="S-001",
            site_type="BACKGROUND",
            latitude=39.80,
            longitude=-105.01,
            population_served=120000,
        ),
        ADMIN_HEADERS,
    )
    validate_error(response, ERR_DUPLICATE_SITE_CODE, 409)

    _rows, meta = validate_paginated(
        api.list_sites(PM_HEADERS, {"network_id": site_env.network_id})
    )
    assert meta["total_count"] == 1
    assert site_env.read_network()["total_site_count"] == 1


def test_the_same_site_code_under_another_network_is_accepted(api, site_env):
    """Site-code uniqueness is scoped to the owning network, so the identical
    code is free under a second network.

    PRD 3.2: "The administrator supplies `network_id`, a `site_code` between 1 and 20 characters that must be unique within that network across sites in *any* status — a collision, including with a site long since shut down, is rejected with `ERR_DUPLICATE_SITE_CODE` (HTTP 409) — and a `site_type` naming the siting objective class: `POPULATION_ORIENTED`, `SOURCE_ORIENTED`, `BACKGROUND` or `TRANSPORT`."

    PRD 3.2: "A proposed site enters `status` `PROPOSED` with `siting_waiver_granted` false, and the network's `total_site_count`, `proposed_site_count` and `waiver_required_site_count` are recomputed."

    Design: Corner/validations/the_same_site_code_in_a_different_network_is_accepted
    """
    other_network = create_network(api, name="Second Ambient Network", agency_code="AQ02")

    twin = validate_success(
        api.create_site(
            site_payload(
                other_network["id"],
                site_code="S-001",
                latitude=39.80,
                longitude=-105.01,
                population_served=120000,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert twin["site_code"] == "S-001"
    assert twin["network_id"] == other_network["id"]
    assert twin["status"] == "PROPOSED"

    assert site_env.read_network()["total_site_count"] == 1
    assert get_success_data(api.get_network(other_network["id"], PM_HEADERS))["total_site_count"] == 1


def test_duplicate_occurrence_code_collides_across_methods_of_one_pollutant(api, monitor_env):
    """The occurrence-code key reaches the pollutant through the instrument's
    method, so a second method for the same pollutant does not free the code,
    while the next code up is accepted.

    PRD 3.3: "A `poc` must be at least 1 and at most 9, and the triple of the site, the pollutant reached through the instrument's method, and the `poc` must be unique among instruments that are not decommissioned — a decommissioned instrument frees its code for reuse."

    PRD 3.3: "A collision is rejected with `ERR_DUPLICATE_MONITOR_POC` (HTTP 409)."

    Design: Corner/validations/duplicate_monitor_poc_for_the_same_pollutant_is_rejected
    """
    second_method = create_reference_method(
        api,
        monitor_env.pollutant_id,
        method_code="EQPM-0918-002",
        designation_type="FEM",
    )

    same_method = api.create_monitor(
        monitor_payload(
            monitor_env.site_id,
            monitor_env.method_id,
            poc=1,
            is_primary_for_design_value=False,
            installed_at="2023-01-01T00:00:00Z",
        ),
        ADMIN_HEADERS,
    )
    validate_error(same_method, ERR_DUPLICATE_MONITOR_POC, 409)

    other_method = api.create_monitor(
        monitor_payload(
            monitor_env.site_id,
            second_method["id"],
            poc=1,
            is_primary_for_design_value=False,
            installed_at="2023-01-01T00:00:00Z",
        ),
        ADMIN_HEADERS,
    )
    validate_error(other_method, ERR_DUPLICATE_MONITOR_POC, 409)

    accepted = validate_success(
        api.create_monitor(
            monitor_payload(
                monitor_env.site_id,
                second_method["id"],
                poc=2,
                is_primary_for_design_value=False,
                installed_at="2023-01-01T00:00:00Z",
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["poc"] == 2
    assert accepted["monitor_status"] == "PENDING_APPROVAL"

    _rows, meta = validate_paginated(
        api.list_monitors(PM_HEADERS, {"site_id": monitor_env.site_id})
    )
    assert meta["total_count"] == 2


def test_a_quarter_that_has_not_ended_is_rejected_at_the_boundary(api, monitor_env):
    """At a clock five days into a quarter the current quarter cannot be
    reported, while the quarter that closed on the first of the month can.

    PRD 3.4: "The test is that the first instant of the *following* calendar quarter must be at or before the logical clock; reporting a quarter still in progress is rejected with `ERR_BATCH_PERIOD_NOT_ENDED` (HTTP 422)."

    Design: Corner/validations/a_quarter_that_has_not_ended_is_rejected_at_the_boundary
    """
    # The clock stands at 2026-01-05, so the first instant of 2026 Q2 is still
    # in the future.
    in_progress = api.create_data_batch(
        data_batch_payload(monitor_env.monitor_id, 2026, 1), QA_HEADERS
    )
    validate_error(in_progress, ERR_BATCH_PERIOD_NOT_ENDED, 422)

    # The quarter that ended has its following quarter beginning 2026-01-01,
    # which is at or before the clock.
    finished = validate_success(
        api.create_data_batch(
            data_batch_payload(
                monitor_env.monitor_id,
                2025,
                4,
                scheduled_hour_count=2208,
                quarterly_mean_concentration=8.8,
            ),
            QA_HEADERS,
        ),
        201,
    )
    assert finished["validation_status"] == "RAW"

    _rows, meta = validate_paginated(
        api.list_data_batches(QA_HEADERS, {"monitor_id": monitor_env.monitor_id})
    )
    assert meta["total_count"] == 1


def test_two_items_of_one_bulk_report_may_not_share_a_period(api, monitor_env):
    """Uniqueness is checked against the request's own earlier items, and the
    failure discards the whole report rather than the offending item.

    PRD 3.4: "Items are validated in list order against exactly the same rules that govern a single report, including the requirement that each reported quarter has already ended on the logical clock and the uniqueness of the instrument-year-quarter triple — checked not only against quarters already in the system but also against the request's own earlier items, so two items colliding on the same period fail with `ERR_DUPLICATE_BATCH_PERIOD`."

    PRD 3.4: "If any item fails for any reason, nothing at all is persisted and the first offending item's error is returned; there is no partial quarter set."

    Design: Corner/validations/bulk_ingest_rejects_two_items_colliding_on_the_same_quarter
    """
    response = api.bulk_ingest(
        {
            "monitor_id": monitor_env.monitor_id,
            "batches": [
                {
                    "year": 2024,
                    "quarter": 2,
                    "scheduled_hour_count": 2184,
                    "quarterly_mean_concentration": 9.1,
                },
                {
                    "year": 2024,
                    "quarter": 3,
                    "scheduled_hour_count": 2208,
                    "quarterly_mean_concentration": 9.2,
                },
                {
                    "year": 2024,
                    "quarter": 2,
                    "scheduled_hour_count": 2184,
                    "quarterly_mean_concentration": 9.3,
                },
            ],
        },
        QA_HEADERS,
    )
    validate_error(response, ERR_DUPLICATE_BATCH_PERIOD, 409)

    rows, meta = validate_paginated(
        api.list_data_batches(QA_HEADERS, {"monitor_id": monitor_env.monitor_id})
    )
    # The legal second item is not persisted either.
    assert meta["total_count"] == 0
    assert rows == []


def test_a_replacement_site_is_required_only_for_a_relocation(api, site_env):
    """Omitting the replacement on a relocation and supplying one on a
    shutdown are the same mistake and draw the same refusal.

    PRD 3.9: "`replacement_site_id` names the site that will take over monitoring after a relocation; it is required when `request_type` is `RELOCATION` and must be absent when `request_type` is `SHUTDOWN` or `SEASONAL_SUSPENSION`."

    PRD 3.9: "Either mistake — a relocation without a replacement, or a shutdown or seasonal suspension carrying one — is refused with `ERR_REPLACEMENT_SITE_REQUIRED` (HTTP 422)."

    Design: Corner/validations/relocation_without_a_replacement_and_shutdown_with_one_are_both_rejected
    """
    assessment = validate_success(
        api.create_assessment(assessment_payload(site_env.network_id, 2026), PM_HEADERS), 201
    )

    missing = api.create_change_request(
        change_request_payload(
            site_env.site_id,
            "RELOCATION",
            assessment["id"],
            justification="Probe siting no longer representative",
        ),
        PM_HEADERS,
    )
    validate_error(missing, ERR_REPLACEMENT_SITE_REQUIRED, 422)

    superfluous = api.create_change_request(
        change_request_payload(
            site_env.site_id,
            "SHUTDOWN",
            assessment["id"],
            justification="Redundant with the nearby site",
            replacement_site_id=site_env.site_id,
        ),
        PM_HEADERS,
    )
    validate_error(superfluous, ERR_REPLACEMENT_SITE_REQUIRED, 422)

    _rows, meta = validate_paginated(
        api.list_change_requests(PM_HEADERS, {"site_id": site_env.site_id})
    )
    assert meta["total_count"] == 0


def test_a_design_value_needs_an_instrument_that_reached_service(api, site_env):
    """A nominated instrument that never left approval leaves the candidate
    pool empty, and the refusal comes instead of a row with no sampler.

    PRD 3.7: "Instruments still `PENDING_APPROVAL` or merely `APPROVED` are excluded, because they have never produced regulatory data — and a decommissioned instrument is deliberately kept in the pool, because the data it produced before shutdown remains part of the record."

    PRD 3.7: "If the pool is empty the request is refused with `ERR_PRIMARY_MONITOR_MISSING` (HTTP 422)."

    Design: Corner/validations/design_value_with_no_commissioned_primary_monitor_is_rejected
    """
    monitor = get_success_data(
        api.create_monitor(
            monitor_payload(site_env.site_id, site_env.method_id), ADMIN_HEADERS
        )
    )
    approve_monitor(api, monitor["id"])

    version_before = site_env.site_version()
    response = api.create_design_value(
        design_value_payload(
            site_env.site_id, site_env.pollutant_id, 2025, "WITH_EVENT_DATA", version_before
        ),
        PM_HEADERS,
    )
    validate_error(response, ERR_PRIMARY_MONITOR_MISSING, 422)

    _rows, meta = validate_paginated(
        api.list_design_values(PM_HEADERS, {"site_id": site_env.site_id})
    )
    assert meta["total_count"] == 0

    site = site_env.read_site()
    assert site["version"] == version_before
    assert site["current_attainment_status"] == "UNDETERMINED"


def test_siting_approval_needs_a_waiver_when_a_criterion_fails(api, base_env):
    """A site carrying violation codes cannot be approved on its geometry
    alone, and the same request succeeds once a waiver is granted.

    PRD 3.2: "The criteria are re-evaluated from the site's current geometry before the gate is applied, and the gate is simple: the approval proceeds when `siting_waiver_required` is false, or when the request body carries `waiver_granted` as true."

    PRD 3.2: "Approving a site whose violation list is non-empty without a granted waiver is rejected with `ERR_SITING_CRITERIA_NOT_MET` (HTTP 422)."

    Design: Corner/validations/siting_approval_of_a_violating_site_without_a_waiver_is_rejected
    """
    # A probe below the band and inside the roadway setback; the clearance
    # required against the obstruction is 2 * (6.0 - 1.0) == 10.0 metres, which
    # 12.0 metres still satisfies.
    violating = validate_success(
        api.create_site(
            site_payload(
                base_env.network_id,
                site_code="S-BAD",
                probe_height_m=1.0,
                distance_to_roadway_m=5.0,
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_siting_codes(violating, ["PROBE_HEIGHT", "ROADWAY_SETBACK"])

    refused = api.approve_siting(violating["id"], {"waiver_granted": False}, EPA_HEADERS)
    validate_error(refused, ERR_SITING_CRITERIA_NOT_MET, 422)
    assert get_success_data(api.get_site(violating["id"], PM_HEADERS))["status"] == "PROPOSED"

    approved = validate_success(
        api.approve_siting(
            violating["id"],
            {
                "waiver_granted": True,
                "approval_note": "Regional waiver granted for a legacy shelter",
            },
            EPA_HEADERS,
        )
    )
    assert approved["status"] == "SITING_APPROVED"
    assert approved["siting_waiver_granted"] is True


def test_an_invalidation_range_must_stay_inside_the_scheduled_hours(api, monitor_env):
    """An overrunning range and an empty range are both refused, the upper
    bound is inclusive, and neither refusal touches the quarter.

    PRD 3.4: "The range must satisfy all of: `start_hour_index` at least 0, `end_hour_index` strictly greater than `start_hour_index`, and `end_hour_index` no greater than the quarter's `scheduled_hour_count`."

    PRD 3.4: "An empty, negative or overrunning range is rejected with `ERR_INVALIDATION_RANGE_OUT_OF_BOUNDS` (HTTP 422)."

    Design: Corner/validations/an_invalidation_range_past_the_scheduled_hour_count_is_rejected
    """
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(monitor_env.monitor_id, 2025, 1, scheduled_hour_count=2160),
            QA_HEADERS,
        )
    )
    opening_version = batch["version"]

    overrun = api.create_invalidation(
        batch["id"],
        invalidation_payload(0, 2161, "QC_FAILURE", opening_version),
        QA_HEADERS,
    )
    validate_error(overrun, ERR_INVALIDATION_RANGE_OUT_OF_BOUNDS, 422)

    empty = api.create_invalidation(
        batch["id"],
        invalidation_payload(5, 5, "QC_FAILURE", opening_version),
        QA_HEADERS,
    )
    validate_error(empty, ERR_INVALIDATION_RANGE_OUT_OF_BOUNDS, 422)

    whole_quarter = validate_success(
        api.create_invalidation(
            batch["id"],
            invalidation_payload(0, 2160, "QC_FAILURE", opening_version),
            QA_HEADERS,
        ),
        201,
    )
    assert whole_quarter["hours_affected"] == 2160
    assert whole_quarter["status"] == "APPLIED"

    reread = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert reread["invalidated_hour_count"] == 2160
    assert reread["valid_hour_count"] == 0
    assert_pct(reread["completeness_pct"], 0.0)
    assert reread["regulatory_use_eligible"] is False
    # Only the accepted invalidation moved the quarter's revision counter.
    assert reread["version"] == opening_version + 1


def test_an_exclusion_may_not_intersect_an_applied_invalidation(api, monitor_env):
    """An hour cannot be both invalid and excluded, but the half-open ranges
    carry no buffer, so a nomination that merely abuts is accepted.

    PRD 3.6: "The collision rule forbids the exclusion range from intersecting the range of any applied invalidation on the same quarter, because an hour cannot be both invalid and excluded; a collision yields `ERR_EXCLUSION_OVERLAPS_INVALIDATION` (HTTP 409)."

    PRD 3.6: "An accepted nomination is created with `status` `PROPOSED`, `hours_affected` set to `end_hour_index` less `start_hour_index`, and `effective_at` null."

    Design: Corner/validations/an_exclusion_overlapping_an_applied_invalidation_is_rejected
    """
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(monitor_env.monitor_id, 2025, 1, scheduled_hour_count=2160),
            QA_HEADERS,
        )
    )
    apply_invalidation(api, batch["id"], 0, 100, "QC_FAILURE", QA_HEADERS)

    # The claimed window runs from the quarter's first instant to 2025-01-05,
    # so the projected window ends at hour 96 plus the closing day, hour 120.
    demonstration = get_success_data(
        api.create_demonstration(
            demonstration_payload(
                monitor_env.site_id,
                monitor_env.pollutant_id,
                event_start_date="2025-01-01T00:00:00Z",
                event_end_date="2025-01-05T00:00:00Z",
            ),
            PM_HEADERS,
        )
    )

    overlapping = api.create_exclusion(
        demonstration["id"], exclusion_payload(batch["id"], 50, 120), PM_HEADERS
    )
    validate_error(overlapping, ERR_EXCLUSION_OVERLAPS_INVALIDATION, 409)

    abutting = validate_success(
        api.create_exclusion(
            demonstration["id"], exclusion_payload(batch["id"], 100, 120), PM_HEADERS
        ),
        201,
    )
    assert abutting["hours_affected"] == 20
    assert abutting["status"] == "PROPOSED"

    assert get_success_data(api.get_demonstration(demonstration["id"], PM_HEADERS))["excluded_hour_total"] == 0
    reread = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert reread["event_excluded_hour_count"] == 0
    assert reread["valid_hour_count"] == 2060


def test_an_exclusion_may_not_reach_past_the_projected_event_window(api, monitor_env):
    """The claimed window is projected onto the quarter's hour axis with one
    closing day added, and a nomination ending at that exact bound is accepted.

    PRD 3.6: "The containment rule requires the exclusion to lie inside the demonstration's event window projected onto the quarter's own hour axis: taking the first instant of the quarter as hour zero, `start_hour_index` must be at least the whole number of hours from the start of the quarter to `event_start_date`, and `end_hour_index` must be no greater than the whole number of hours from the start of the quarter to `event_end_date` plus 24 hours — the extra day being the same closing-day allowance the conflict test uses."

    PRD 3.6: "A nomination outside the projected window is rejected with `ERR_EVENT_WINDOW_OUTSIDE_BATCH_PERIOD` (HTTP 422)."

    Design: Corner/validations/an_exclusion_outside_the_mapped_event_window_is_rejected
    """
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(monitor_env.monitor_id, 2025, 1, scheduled_hour_count=2160),
            QA_HEADERS,
        )
    )
    demonstration = get_success_data(
        api.create_demonstration(
            demonstration_payload(
                monitor_env.site_id,
                monitor_env.pollutant_id,
                event_start_date="2025-01-01T00:00:00Z",
                event_end_date="2025-01-05T00:00:00Z",
            ),
            PM_HEADERS,
        )
    )

    beyond = api.create_exclusion(
        demonstration["id"], exclusion_payload(batch["id"], 0, 200), PM_HEADERS
    )
    validate_error(beyond, ERR_EVENT_WINDOW_OUTSIDE_BATCH_PERIOD, 422)

    # 96 hours reach 2025-01-05, and the closing day carries the bound to 120.
    at_the_bound = validate_success(
        api.create_exclusion(
            demonstration["id"], exclusion_payload(batch["id"], 0, 120), PM_HEADERS
        ),
        201,
    )
    assert at_the_bound["hours_affected"] == 120

    _rows, meta = validate_paginated(api.list_batch_exclusions(batch["id"], QA_HEADERS))
    assert meta["total_count"] == 1


def test_a_finalized_design_value_key_blocks_only_its_own_variant(api, data_env):
    """The uniqueness guard keys on the site, pollutant, period and variant, so
    the other variant of the same period is still computable.

    PRD 3.7: "A computation against a finalized key is refused with `ERR_DESIGN_VALUE_FINALIZED` (HTTP 409), but a site with no eligible primary sampler surfaces its own refusal first."

    PRD 3.7: "Otherwise the already-rounded annual statistics are summed and divided by `design_value_years`, and that mean is then **truncated** toward zero to the pollutant's `rounding_decimals` to produce `design_value`."

    Design: Corner/validations/a_design_value_for_an_already_finalized_key_is_rejected
    """
    provisional = compute_design_value(data_env, period_end_year=2025, variant="WITH_EVENT_DATA")
    assert provisional["status"] == "PROVISIONAL"

    finalized = validate_success(
        api.finalize_design_value(
            provisional["id"], {"finalization_note": "Regional determination"}, EPA_HEADERS
        )
    )
    assert finalized["status"] == "FINAL"
    assert finalized["design_value"] == pytest.approx(9.1, abs=0.01)
    assert finalized["complete_year_count"] == 3

    site_version = data_env.site_version()
    repeat = api.create_design_value(
        design_value_payload(
            data_env.site_id, data_env.pollutant_id, 2025, "WITH_EVENT_DATA", site_version
        ),
        PM_HEADERS,
    )
    validate_error(repeat, ERR_DESIGN_VALUE_FINALIZED, 409)

    other_variant = validate_success(
        api.create_design_value(
            design_value_payload(
                data_env.site_id,
                data_env.pollutant_id,
                2025,
                "EXCLUDING_CONCURRED_EVENTS",
                site_version,
            ),
            PM_HEADERS,
        ),
        201,
    )
    assert other_variant["variant"] == "EXCLUDING_CONCURRED_EVENTS"
    assert other_variant["status"] == "PROVISIONAL"

    _rows, meta = validate_paginated(
        api.list_design_values(
            PM_HEADERS, {"site_id": data_env.site_id, "period_end_year": 2025}
        )
    )
    assert meta["total_count"] == 2


def test_finalizing_a_design_value_below_the_required_years_is_rejected(api):
    """A provisional row resting on two complete years cannot be finalized
    against a three-year standard, and the refusal leaves it provisional.

    PRD 3.7: "It is permitted only when `complete_year_count` equals the pollutant's `design_value_years`; a row resting on fewer complete years is refused with `ERR_DESIGN_VALUE_INCOMPLETE` (HTTP 422)."

    Design: Corner/validations/finalizing_before_three_complete_years_is_rejected
    """
    eleven = [
        dict(quarter)
        for quarter in WORKED_EXAMPLE_QUARTERS
        if not (quarter["year"] == 2024 and quarter["quarter"] == 4)
    ]
    env = twelve_validated_quarters(api, batches=eleven)

    provisional = compute_design_value(env, period_end_year=2025, variant="WITH_EVENT_DATA")
    assert provisional["complete_year_count"] == 2
    assert provisional["design_value"] is None

    response = api.finalize_design_value(provisional["id"], {}, EPA_HEADERS)
    validate_error(response, ERR_DESIGN_VALUE_INCOMPLETE, 422)

    reread = get_success_data(api.get_design_value(provisional["id"], PM_HEADERS))
    assert reread["status"] == "PROVISIONAL"
    assert reread["complete_year_count"] == 2
    assert reread["design_value"] is None


def test_bulk_validation_needs_at_least_one_raw_quarter(api, monitor_env):
    """The bulk selector sees only raw quarters, so the very same call that
    succeeded once is refused immediately afterwards.

    PRD 3.5: "The selector matches quarters of that instrument, optionally restricted to that year, whose `validation_status` is `RAW`; quarters sitting in `IN_VALIDATION`, `VALIDATED`, `REOPENED` or `INVALIDATED` are silently skipped rather than rejected."

    PRD 3.5: "If the selector matches no raw quarter at all, the request is rejected with `ERR_NO_ELIGIBLE_BATCHES` (HTTP 422)."

    Design: Corner/validations/bulk_validate_with_no_raw_batches_left_is_rejected
    """
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(monitor_env.monitor_id, 2025, 1, scheduled_hour_count=2160),
            QA_HEADERS,
        )
    )

    moved = validate_success(api.bulk_validate({"monitor_id": monitor_env.monitor_id}, QA_HEADERS))
    assert len(moved) == 1
    assert moved[0]["id"] == batch["id"]

    reread = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert reread["validation_status"] == "VALIDATED"
    assert reread["validated_by_user_id"] == "qa-1"

    again = api.bulk_validate({"monitor_id": monitor_env.monitor_id}, QA_HEADERS)
    validate_error(again, ERR_NO_ELIGIBLE_BATCHES, 422)


def test_a_package_with_one_ineligible_quarter_cannot_be_submitted(api):
    """A single member quarter below the completeness threshold blocks the
    submission even though the package has members, and no quarter moves.

    PRD 3.8: "The rollup is refreshed immediately before the readiness gate is applied, and the gate requires `certification_ready` to be true; a package that is not ready is refused with `ERR_PACKAGE_NOT_READY` (HTTP 422)."

    PRD 3.8: "On success every selected quarter whose `submission_status` is `UNSUBMITTED` advances to `SUBMITTED` while its `validation_status` stays at `VALIDATED` — the dimensions remain parallel and independent — and both the package's `version` and each moved quarter's `version` increment by 1."

    Design: Corner/validations/submitting_a_package_below_the_completeness_threshold_is_rejected
    """
    env = canonical_environment(api)
    complete = get_success_data(
        api.create_data_batch(
            data_batch_payload(env.monitor_id, 2025, 1, scheduled_hour_count=2160), QA_HEADERS
        )
    )
    halved = get_success_data(
        api.create_data_batch(
            data_batch_payload(
                env.monitor_id, 2025, 2, scheduled_hour_count=2184, quarterly_mean_concentration=9.1
            ),
            QA_HEADERS,
        )
    )
    apply_invalidation(api, halved["id"], 0, 1092, "QC_FAILURE", QA_HEADERS)
    # A different officer accepts the quarters, because the one who applied the
    # invalidation may not validate them.
    get_success_data(api.bulk_validate({"monitor_id": env.monitor_id, "year": 2025}, QA2_HEADERS))

    open_package(env, year=2025)
    response = api.submit_package(env.package_id, {"submission_note": "Annual data set"}, PM_HEADERS)
    validate_error(response, ERR_PACKAGE_NOT_READY, 422)

    package = get_success_data(api.get_package(env.package_id, PM_HEADERS))
    assert package["status"] == "DRAFT"
    assert package["certification_ready"] is False
    assert package["included_batch_count"] == 2
    assert package["eligible_batch_count"] == 1

    for batch_id in (complete["id"], halved["id"]):
        row = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
        assert row["validation_status"] == "VALIDATED"
        assert row["submission_status"] == "UNSUBMITTED"


def test_reopening_a_certified_quarter_is_rejected(api, data_env):
    """Certification is the point of no return: a quarter carried to the
    national database can no longer be pulled back for review.

    PRD 3.5: "Certified data is immutable: if the quarter's `submission_status` is `CERTIFIED` the reopen is refused with `ERR_BATCH_CERTIFIED` (HTTP 409), and this check is what makes the certification step of §3.8 a genuine point of no return."

    PRD 3.8: "On success `certified_by_user_id` and `certified_at` are stamped, every selected quarter whose `submission_status` is `SUBMITTED` advances to `CERTIFIED`, and each of those quarters becomes permanently unreopenable as described in §3.5."

    Design: Corner/validations/reopening_a_certified_quarter_is_rejected
    """
    open_package(data_env, year=2025)
    validate_success(
        api.submit_package(data_env.package_id, {"submission_note": "2025 annual data set"}, PM_HEADERS)
    )
    # A manager who did not accept the quarters performs the certification.
    certified = validate_success(
        api.certify_package(
            data_env.package_id,
            {"certification_statement": "I certify the 2025 data set"},
            PM2_HEADERS,
        )
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "pm-2"

    batch_id = data_env.batch_id(2025, 1)
    assert get_success_data(api.get_data_batch(batch_id, QA_HEADERS))["submission_status"] == "CERTIFIED"

    response = api.reopen_batch(
        batch_id, {"reopen_reason": "Late instrument audit finding"}, QA_HEADERS
    )
    validate_error(response, ERR_BATCH_CERTIFIED, 409)

    reread = get_success_data(api.get_data_batch(batch_id, QA_HEADERS))
    assert reread["validation_status"] == "VALIDATED"
    assert reread["submission_status"] == "CERTIFIED"


def test_a_written_off_quarter_accepts_no_further_invalidation(api, monitor_env):
    """Once a quarter has been rejected wholesale its hour ledger is closed,
    and a current revision counter does not reopen it.

    PRD 3.5: "Rejecting a quarter wholesale advances either `IN_VALIDATION → INVALIDATED` or `REOPENED → INVALIDATED`, optionally with an `invalidation_note`."

    PRD 3.4: "A quarter whose `validation_status` is already `INVALIDATED` accepts no invalidation creation, no invalidation withdrawal, and no event-exclusion attachment; all three are rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/validations/invalidating_hours_on_an_invalidated_batch_is_rejected
    """
    batch = get_success_data(
        api.create_data_batch(
            data_batch_payload(monitor_env.monitor_id, 2025, 1, scheduled_hour_count=2160),
            QA_HEADERS,
        )
    )
    get_success_data(api.begin_validation(batch["id"], {}, QA_HEADERS))
    written_off = get_success_data(
        api.invalidate_batch(
            batch["id"], {"invalidation_note": "Quarter unusable after an audit failure"}, QA_HEADERS
        )
    )
    assert written_off["validation_status"] == "INVALIDATED"

    # The supplied revision counter is the current one, so the refusal is the
    # state guard and not a concurrency conflict.
    response = api.create_invalidation(
        batch["id"],
        invalidation_payload(0, 100, "QC_FAILURE", batch_version(api, batch["id"])),
        QA_HEADERS,
    )
    validate_error(response, ERR_INVALID_STATE, 409)

    _rows, meta = validate_paginated(api.list_batch_invalidations(batch["id"], QA_HEADERS))
    assert meta["total_count"] == 0


def test_a_relocation_to_a_merely_proposed_replacement_is_rejected(api, site_env):
    """The replacement site must itself have cleared siting review, and the
    refusal leaves both the request and the target site untouched.

    PRD 3.9: "Then the referential gates, in priority order: the cited assessment must exist, have `status` `APPROVED` and belong to the same network as the target site, or the answer is `ERR_ASSESSMENT_NOT_APPROVED` (HTTP 422); and for a relocation the nominated replacement site must have `status` `SITING_APPROVED` or `OPERATING` and belong to the same network, or the answer is `ERR_REPLACEMENT_SITE_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/validations/relocation_to_a_proposed_replacement_site_is_rejected
    """
    replacement = get_success_data(
        api.create_site(
            site_payload(
                site_env.network_id,
                site_code="S-002",
                latitude=39.70,
                longitude=-104.90,
                population_served=90000,
            ),
            ADMIN_HEADERS,
        )
    )
    assessment = approved_assessment(site_env, cycle_year=2026)
    assert assessment["status"] == "APPROVED"

    request = get_success_data(
        api.create_change_request(
            change_request_payload(
                site_env.site_id,
                "RELOCATION",
                site_env.assessment_id,
                justification="Shelter lease terminated",
                replacement_site_id=replacement["id"],
            ),
            PM_HEADERS,
        )
    )
    validate_success(api.submit_change_request(request["id"], {}, PM_HEADERS))

    response = api.decide_change_request(
        request["id"], {"decision": "APPROVE", "decision_note": "Relocation reviewed"}, EPA_HEADERS
    )
    validate_error(response, ERR_REPLACEMENT_SITE_NOT_ELIGIBLE, 422)

    assert get_success_data(api.get_site(replacement["id"], PM_HEADERS))["status"] == "PROPOSED"
    assert get_success_data(api.get_change_request(request["id"], PM_HEADERS))["status"] == "SUBMITTED"
    assert site_env.read_site()["status"] == "OPERATING"


def test_a_change_request_on_a_site_that_never_opened_cannot_be_submitted(api, site_env):
    """Submission demands an operating target, so a site that only cleared
    siting review cannot be carried into review.

    PRD 3.9: "Submitting the request advances `DRAFT → SUBMITTED`, optionally with a `submission_note`, and requires that the target site is still `OPERATING`; a request submitted against a site in any other status is refused with `ERR_SITE_NOT_OPERATING` (HTTP 409)."

    Design: Corner/validations/submitting_a_change_request_for_a_non_operating_site_is_rejected
    """
    idle = get_success_data(
        api.create_site(
            site_payload(
                site_env.network_id,
                site_code="S-002",
                latitude=39.70,
                longitude=-104.90,
                population_served=90000,
            ),
            ADMIN_HEADERS,
        )
    )
    approve_siting(api, idle["id"])
    assert get_success_data(api.get_site(idle["id"], PM_HEADERS))["status"] == "SITING_APPROVED"

    assessment = validate_success(
        api.create_assessment(assessment_payload(site_env.network_id, 2026), PM_HEADERS), 201
    )
    request = get_success_data(
        api.create_change_request(
            change_request_payload(
                idle["id"],
                "SHUTDOWN",
                assessment["id"],
                justification="Site never became operational",
            ),
            PM_HEADERS,
        )
    )

    response = api.submit_change_request(request["id"], {}, PM_HEADERS)
    validate_error(response, ERR_SITE_NOT_OPERATING, 409)

    assert get_success_data(api.get_change_request(request["id"], PM_HEADERS))["status"] == "DRAFT"
