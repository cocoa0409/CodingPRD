"""Lifecycle behaviour: declared transitions, guards, terminal states and cycles.

Every assertion in this module is derived from the PRD narrative alone. State is
built through the declared HTTP surface only, because the server is restarted
with an empty database before each test.
"""

from datetime import datetime

from test_helpers import (
    CANONICAL_CLOCK,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    approve_monitor,
    approve_siting,
    assert_annual_statistics,
    assert_batch_dimensions,
    assert_pct,
    assert_ratio_4dp,
    assert_site_census_partitioned,
    assessment_payload,
    change_request_payload,
    create_monitor,
    create_operating_monitor,
    create_site,
    data_batch_payload,
    demonstration_payload,
    design_value_payload,
    exclusion_payload,
    find_by_id,
    get_success_data,
    invalidation_payload,
    package_payload,
    set_clock,
    span_check_payload,
    submitted_package,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable moment in time."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_siting_approval_moves_a_proposed_site_to_siting_approved(
    api, base_env, epa_headers, pm_headers
):
    """Regional approval advances a proposed site and shifts the network census.

    PRD §3.2: "Siting approval belongs to the `EpaRegionalReviewer` and moves a site from `PROPOSED` to `SITING_APPROVED`."
    PRD §3.2: "On success `siting_waiver_granted` takes whatever value `waiver_granted` carried, the network's `proposed_site_count` decrements by 1 and its `approved_site_count` increments by 1, `waiver_required_site_count` is recomputed, and both the site's `version` and the network's `version` increment by 1."

    Design: Corner/state_machines/siting_approval_moves_a_proposed_site_to_siting_approved
    """
    site = create_site(api, base_env.network_id)
    assert site["status"] == "PROPOSED"
    assert site["version"] == 1

    approved = validate_success(
        api.approve_siting(
            site["id"],
            {"waiver_granted": False, "approval_note": "Siting criteria met"},
            epa_headers,
        )
    )
    assert approved["status"] == "SITING_APPROVED"
    assert approved["siting_waiver_granted"] is False
    assert approved["version"] == 2

    network = get_success_data(api.get_network(base_env.network_id, pm_headers))
    assert network["proposed_site_count"] == 0
    assert network["approved_site_count"] == 1
    assert network["operating_site_count"] == 0
    assert network["total_site_count"] == 1
    assert_site_census_partitioned(network)


def test_commence_operations_on_a_proposed_site_is_rejected(api, base_env, pm_headers):
    """Bringing a site into service is refused while it is still merely proposed.

    PRD §3.2: "Bringing a site into service is a `ProgramManager` action that advances `SITING_APPROVED → OPERATING`, optionally annotated with an `operations_note`."
    PRD §3.2: "It stamps `operations_start_at` from the logical clock — the field is null until then — and it is safe with respect to siting because either the violation list was empty or a waiver was already granted at approval time."
    PRD §2.11: "After concurrency come the state checks — the target's own from-state and the cross-row preconditions its transition declares (`ERR_INVALID_STATE`), whether the target is already terminal (`ERR_ALREADY_TERMINAL`), and the specific state guards for certified quarters (`ERR_BATCH_CERTIFIED`), non-operating sites (`ERR_SITE_NOT_OPERATING`) and unvalidated member quarters (`ERR_MEMBER_BATCH_NOT_VALIDATED`)."

    Design: Corner/state_machines/commence_operations_on_a_proposed_site_is_rejected
    """
    site = create_site(api, base_env.network_id)

    validate_error(
        api.commence_operations(site["id"], {"operations_note": "Premature"}, pm_headers),
        ERR_INVALID_STATE,
        409,
    )

    unchanged = get_success_data(api.get_site(site["id"], pm_headers))
    assert unchanged["status"] == "PROPOSED"
    assert unchanged["operations_start_at"] is None
    assert unchanged["version"] == 1

    network = get_success_data(api.get_network(base_env.network_id, pm_headers))
    assert network["operating_site_count"] == 0
    assert network["proposed_site_count"] == 1
    assert_site_census_partitioned(network)


def test_a_second_siting_approval_on_the_same_site_is_rejected(
    api, base_env, epa_headers, pm_headers
):
    """Replaying the approval is refused rather than silently repeating it.

    PRD §3.2: "Siting approval belongs to the `EpaRegionalReviewer` and moves a site from `PROPOSED` to `SITING_APPROVED`."
    PRD §2.11: "After concurrency come the state checks — the target's own from-state and the cross-row preconditions its transition declares (`ERR_INVALID_STATE`), whether the target is already terminal (`ERR_ALREADY_TERMINAL`), and the specific state guards for certified quarters (`ERR_BATCH_CERTIFIED`), non-operating sites (`ERR_SITE_NOT_OPERATING`) and unvalidated member quarters (`ERR_MEMBER_BATCH_NOT_VALIDATED`)."

    Design: Corner/state_machines/a_second_siting_approval_on_the_same_site_is_rejected
    """
    site = create_site(api, base_env.network_id)
    approve_siting(api, site["id"])

    validate_error(
        api.approve_siting(site["id"], {"waiver_granted": False}, epa_headers),
        ERR_INVALID_STATE,
        409,
    )

    unchanged = get_success_data(api.get_site(site["id"], pm_headers))
    assert unchanged["status"] == "SITING_APPROVED"
    assert unchanged["version"] == 2

    network = get_success_data(api.get_network(base_env.network_id, pm_headers))
    assert network["approved_site_count"] == 1
    assert network["proposed_site_count"] == 0
    assert_site_census_partitioned(network)


def test_newly_created_rows_start_in_their_declared_initial_states(
    api, base_env, admin_headers, qa_headers, pm_headers
):
    """Creation writes the declared opening state on every lifecycle-bearing row.

    PRD §3.1: "A newly registered method enters `designation_status` `DESIGNATED` with `designation_change_count` at 0 and `withdrawn_on` null."
    PRD §3.2: "A proposed site enters `status` `PROPOSED` with `siting_waiver_granted` false, and the network's `total_site_count`, `proposed_site_count` and `waiver_required_site_count` are recomputed."
    PRD §3.3: "A newly installed instrument enters `monitor_status` `PENDING_APPROVAL` with all four quality-control timestamps — `last_calibration_at`, `last_span_check_at`, `last_zero_check_at` and `last_maintenance_at` — null, with `consecutive_qc_failure_count` at 0, with `out_of_service_day_count` at 0, and with `out_of_service_since` null."
    PRD §3.4: "A quarter is born with `validation_status` `RAW` and `submission_status` `UNSUBMITTED`, with `reopen_count` at 0 and `invalidation_applied_by_user_ids` an empty list."
    PRD §3.4: "An accepted invalidation is created with `status` `APPLIED`, with `hours_affected` set to `end_hour_index` less `start_hour_index`, with `data_batch_id` naming the quarter, and with `applied_by_user_id` set to the calling `X-User-ID`."
    PRD §3.6: "A new demonstration enters `status` `DRAFT` with `info_request_count` at 0 and `excluded_hour_total` at 0."
    PRD §3.9: "Adequacy scoring runs immediately, and the cycle enters `status` `DRAFT` with `return_count` at 0."
    PRD §3.9: "A new request enters `status` `DRAFT` with `revision_request_count` at 0."
    PRD §3.8: "First, `certification_deadline` is pinned to the first of May of the year following `year`, at midnight UTC."
    PRD §3.8: "The package enters `status` `DRAFT` with `rejection_count` at 0."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    method = get_success_data(api.get_reference_method(base_env.method_id, admin_headers))
    assert method["designation_status"] == "DESIGNATED"
    assert method["designation_change_count"] == 0
    assert method["withdrawn_on"] is None

    site = create_site(api, base_env.network_id)
    assert site["status"] == "PROPOSED"
    assert site["siting_waiver_granted"] is False

    monitor = create_monitor(api, site["id"], base_env.method_id)
    assert monitor["monitor_status"] == "PENDING_APPROVAL"
    assert monitor["consecutive_qc_failure_count"] == 0
    assert monitor["out_of_service_day_count"] == 0
    assert monitor["last_span_check_at"] is None
    assert monitor["out_of_service_since"] is None

    batch = validate_success(
        api.create_data_batch(data_batch_payload(monitor["id"], 2025, 1), qa_headers), 201
    )
    assert_batch_dimensions(batch, "RAW", "UNSUBMITTED")
    assert batch["reopen_count"] == 0

    invalidation = validate_success(
        api.create_invalidation(
            batch["id"], invalidation_payload(0, 24, "QC_FAILURE", batch["version"]), qa_headers
        ),
        201,
    )
    assert invalidation["status"] == "APPLIED"
    assert invalidation["hours_affected"] == 24

    demonstration = validate_success(
        api.create_demonstration(
            demonstration_payload(
                site["id"],
                base_env.pollutant_id,
                event_start_date="2025-01-05T00:00:00Z",
                event_end_date="2025-01-08T00:00:00Z",
                narrative="Smoke intrusion",
            ),
            pm_headers,
        ),
        201,
    )
    assert demonstration["status"] == "DRAFT"
    assert demonstration["info_request_count"] == 0

    assessment = validate_success(
        api.create_assessment(assessment_payload(base_env.network_id, 2026), pm_headers), 201
    )
    assert assessment["status"] == "DRAFT"
    assert assessment["return_count"] == 0
    assert assessment["submitted_at"] is None

    change_request = validate_success(
        api.create_change_request(
            change_request_payload(
                site["id"], "SHUTDOWN", assessment["id"], justification="Lease ended"
            ),
            pm_headers,
        ),
        201,
    )
    assert change_request["status"] == "DRAFT"
    assert change_request["revision_request_count"] == 0
    assert change_request["effective_at"] is None

    package = validate_success(
        api.create_package(
            package_payload(base_env.network_id, base_env.pollutant_id, 2025), pm_headers
        ),
        201,
    )
    assert package["status"] == "DRAFT"
    assert package["rejection_count"] == 0
    assert _instant(package["certification_deadline"]) == _instant("2026-05-01T00:00:00Z")


def test_withdrawn_reference_method_rejects_a_further_designation_change(
    api, base_env, admin_headers, epa_headers
):
    """A withdrawn method is closed to any later designation change.

    PRD §3.1: "Either state may move to `WITHDRAWN`, which is terminal: no designation change is accepted on a method that has already been withdrawn."
    PRD §3.1: "Attempting a change whose declared source state does not match the method's present `designation_status` is rejected with `ERR_INVALID_STATE` (HTTP 409); attempting any change on a `WITHDRAWN` method is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §3.1: "A change to `WITHDRAWN` additionally sets `withdrawn_on` to the logical-clock instant; a change to any other status leaves `withdrawn_on` null."
    PRD §3.1: "Every accepted change increments `designation_change_count` by 1 and increments the method's `version` by 1."

    Design: Corner/state_machines/withdrawn_reference_method_rejects_a_further_designation_change
    """
    withdrawn = validate_success(
        api.change_designation(
            base_env.method_id,
            {"new_designation_status": "WITHDRAWN", "determination_note": "Method retired"},
            epa_headers,
        )
    )
    assert withdrawn["designation_status"] == "WITHDRAWN"

    validate_error(
        api.change_designation(
            base_env.method_id,
            {"new_designation_status": "DESIGNATED", "determination_note": "Attempted restoration"},
            epa_headers,
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    method = get_success_data(api.get_reference_method(base_env.method_id, admin_headers))
    assert method["designation_status"] == "WITHDRAWN"
    assert method["designation_change_count"] == 1
    assert _instant(method["withdrawn_on"]) == _instant(CANONICAL_CLOCK)


def test_monitor_commission_before_the_site_operates_is_rejected(
    api, base_env, tech_headers, pm_headers
):
    """Commissioning waits for the site itself to be operating, not merely approved.

    PRD §3.3: "Here the site must be fully `OPERATING`, not merely approved, and the method-designation test applies again."
    PRD §3.3: "On success the site's `operating_monitor_count` increments by 1, both the instrument's and the site's `version` increment, and the instrument becomes visible to the primary-monitor selector described in §3.7."
    PRD §3.3: "On success both postures are computed with `last_span_check_at` still null, so the baseline is `installed_at`, and the network's `delinquent_monitor_count` is recomputed."
    PRD §3.3: "An elapsed-days figure no greater than the interval yields `QC_CURRENT`; an elapsed figure greater than the interval but no greater than the interval plus a grace period of one week yields `QC_DUE`; anything beyond that yields `QC_DELINQUENT`."
    PRD §2.11: "After concurrency come the state checks — the target's own from-state and the cross-row preconditions its transition declares (`ERR_INVALID_STATE`), whether the target is already terminal (`ERR_ALREADY_TERMINAL`), and the specific state guards for certified quarters (`ERR_BATCH_CERTIFIED`), non-operating sites (`ERR_SITE_NOT_OPERATING`) and unvalidated member quarters (`ERR_MEMBER_BATCH_NOT_VALIDATED`)."

    Design: Corner/state_machines/monitor_commission_before_the_site_operates_is_rejected
    """
    site = create_site(api, base_env.network_id)
    approve_siting(api, site["id"])

    # Installed fourteen days before the logical clock, exactly the span-check interval.
    monitor = create_monitor(
        api, site["id"], base_env.method_id, installed_at="2025-12-22T00:00:00Z"
    )
    approve_monitor(api, monitor["id"])

    validate_error(
        api.commission_monitor(
            monitor["id"], {"commission_note": "Premature commissioning"}, tech_headers
        ),
        ERR_INVALID_STATE,
        409,
    )

    unchanged = get_success_data(api.get_monitor(monitor["id"], pm_headers))
    assert unchanged["monitor_status"] == "APPROVED"
    assert unchanged["qc_posture"] == "QC_CURRENT"

    parent = get_success_data(api.get_site(site["id"], pm_headers))
    assert parent["status"] == "SITING_APPROVED"
    assert parent["operating_monitor_count"] == 0


def test_demonstration_submit_without_a_proposed_exclusion_is_rejected(
    api, monitor_env, qa_headers, pm_headers
):
    """Both submission guards refuse the demonstration and leave the hours untouched.

    PRD §3.6: "Two conditions guard the first submission: at least one exclusion with `status` `PROPOSED` must exist under the demonstration, and `clear_causal_relationship` must be true."
    PRD §3.6: "A submission failing either is rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "An accepted nomination is created with `status` `PROPOSED`, `hours_affected` set to `end_hour_index` less `start_hour_index`, and `effective_at` null."
    PRD §3.4: "Third, `event_excluded_hour_count` is the total of `hours_affected` over every event exclusion on this quarter that has become effective; proposed and rejected exclusions contribute nothing."
    PRD §3.4: "Sixth, `completeness_pct` is `valid_hour_count` divided by `adjusted_scheduled_hour_count`, multiplied by 100 and rounded to one decimal place, except that when `adjusted_scheduled_hour_count` is zero the value is 0.0 rather than an error."

    Design: Corner/state_machines/demonstration_submit_without_a_proposed_exclusion_is_rejected
    """
    batch = validate_success(
        api.create_data_batch(
            data_batch_payload(
                monitor_env.monitor_id,
                2024,
                3,
                scheduled_hour_count=2208,
                quarterly_mean_concentration=9.2,
                quarterly_mean_concentration_event_adjusted=7.9,
            ),
            qa_headers,
        ),
        201,
    )

    without_exclusions = validate_success(
        api.create_demonstration(
            demonstration_payload(
                monitor_env.site_id,
                monitor_env.pollutant_id,
                narrative="Regional wildfire smoke plume",
            ),
            pm_headers,
        ),
        201,
    )
    without_causality = validate_success(
        api.create_demonstration(
            demonstration_payload(
                monitor_env.site_id,
                monitor_env.pollutant_id,
                event_type="HIGH_WIND_DUST",
                narrative="High wind dust entrainment",
                clear_causal_relationship=False,
            ),
            pm_headers,
        ),
        201,
    )
    nomination = validate_success(
        api.create_exclusion(
            without_causality["id"], exclusion_payload(batch["id"], 1008, 1200), pm_headers
        ),
        201,
    )

    validate_error(
        api.submit_demonstration(
            without_exclusions["id"], {"submission_note": "No exclusions attached"}, pm_headers
        ),
        ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api.submit_demonstration(
            without_causality["id"], {"submission_note": "Causality not established"}, pm_headers
        ),
        ERR_INVALID_STATE,
        409,
    )

    first = get_success_data(api.get_demonstration(without_exclusions["id"], pm_headers))
    assert first["status"] == "DRAFT"
    assert first["info_request_count"] == 0

    second = get_success_data(api.get_demonstration(without_causality["id"], pm_headers))
    assert second["status"] == "DRAFT"

    rows, _meta = validate_paginated(
        api.list_demonstration_exclusions(without_causality["id"], pm_headers)
    )
    still_proposed = find_by_id(rows, nomination["id"])
    assert still_proposed is not None
    assert still_proposed["status"] == "PROPOSED"
    assert still_proposed["effective_at"] is None

    refreshed = get_success_data(api.get_data_batch(batch["id"], qa_headers))
    assert refreshed["event_excluded_hour_count"] == 0
    assert_pct(refreshed["completeness_pct"], 100.0)


def test_certified_package_rejects_a_regional_rejection(
    api, data_env, qa_headers, pm_headers, epa_headers
):
    """Certification closes the package: a later rejection cannot reopen it.

    PRD §3.8: "On success `certified_by_user_id` and `certified_at` are stamped, every selected quarter whose `submission_status` is `SUBMITTED` advances to `CERTIFIED`, and each of those quarters becomes permanently unreopenable as described in §3.5."
    PRD §3.8: "`CERTIFIED` is terminal for a package."
    PRD §3.8: "Rejection belongs to the `EpaRegionalReviewer`, requires a `rejection_reason`, and returns the package `SUBMITTED → DRAFT` rather than moving it to any distinct rejected state."
    PRD §3.8: "From that selection, `included_batch_count` is the number of selected quarters and `eligible_batch_count` is the number of them whose `regulatory_use_eligible` is true."
    PRD §3.8: "`rollup_completeness_pct` is computed from summed hours, not by averaging per-quarter percentages: sum `valid_hour_count` across the selected quarters, sum `adjusted_scheduled_hour_count` across the same quarters, divide the first total by the second, multiply by 100 and round to one decimal place — with the value taken as 0.0 when the second total is zero."
    PRD §2.5: "The service does not read wall-clock time."
    PRD §2.11: "After concurrency come the state checks — the target's own from-state and the cross-row preconditions its transition declares (`ERR_INVALID_STATE`), whether the target is already terminal (`ERR_ALREADY_TERMINAL`), and the specific state guards for certified quarters (`ERR_BATCH_CERTIFIED`), non-operating sites (`ERR_SITE_NOT_OPERATING`) and unvalidated member quarters (`ERR_MEMBER_BATCH_NOT_VALIDATED`)."

    Design: Corner/state_machines/certified_package_rejects_a_regional_rejection
    """
    submitted_package(data_env, year=2025, submission_note="Annual data set submitted")
    certified = validate_success(
        api.certify_package(
            data_env.package_id,
            {"certification_statement": "The 2025 PM25 data set is complete and accurate"},
            pm_headers,
        )
    )
    assert certified["status"] == "CERTIFIED"

    validate_error(
        api.reject_package(
            data_env.package_id, {"rejection_reason": "Late review finding"}, epa_headers
        ),
        ERR_ALREADY_TERMINAL,
        409,
    )

    package = get_success_data(api.get_package(data_env.package_id, pm_headers))
    assert package["status"] == "CERTIFIED"
    assert package["rejection_count"] == 0
    assert package["certified_by_user_id"] == "pm-1"
    assert _instant(package["certified_at"]) == _instant(CANONICAL_CLOCK)
    assert package["included_batch_count"] == 4
    assert package["eligible_batch_count"] == 4
    assert_pct(package["rollup_completeness_pct"], 100.0)

    rows, meta = validate_paginated(
        api.list_data_batches(qa_headers, params={"monitor_id": data_env.monitor_id, "year": 2025})
    )
    assert meta["total_count"] == 4
    for quarter in rows:
        assert_batch_dimensions(quarter, "VALIDATED", "CERTIFIED")


def test_certification_package_rejection_demotes_submitted_quarters_to_unsubmitted(
    api, data_env, qa_headers, pm_headers, epa_headers
):
    """Rejection returns the package to draft and only withdraws the year it covered.

    PRD §3.8: "Rejection belongs to the `EpaRegionalReviewer`, requires a `rejection_reason`, and returns the package `SUBMITTED → DRAFT` rather than moving it to any distinct rejected state."
    PRD §3.8: "`rejection_count` increments by 1, and — this is the cascade that catches implementers out — every quarter matching the package's network, pollutant and year whose `submission_status` is `SUBMITTED` is demoted back to `UNSUBMITTED`, while its `validation_status` stays at `VALIDATED`."
    PRD §3.8: "From that selection, `included_batch_count` is the number of selected quarters and `eligible_batch_count` is the number of them whose `regulatory_use_eligible` is true."
    PRD §3.8: "Finally, `certification_ready` is true exactly when `included_batch_count` is at least 1 **and** `eligible_batch_count` equals `included_batch_count`; a single member quarter below its pollutant's completeness threshold makes the whole package unready, as does a package with no members at all."

    Design: Corner/state_machines/certification_package_rejection_demotes_submitted_quarters_to_unsubmitted
    """
    submitted_package(data_env, year=2025, submission_note="Annual data set submitted")

    rejected = validate_success(
        api.reject_package(
            data_env.package_id, {"rejection_reason": "Quarter 3 narrative missing"}, epa_headers
        )
    )
    assert rejected["status"] == "DRAFT"
    assert rejected["rejection_count"] == 1

    covered, covered_meta = validate_paginated(
        api.list_data_batches(qa_headers, params={"monitor_id": data_env.monitor_id, "year": 2025})
    )
    assert covered_meta["total_count"] == 4
    for quarter in covered:
        assert_batch_dimensions(quarter, "VALIDATED", "UNSUBMITTED")
        assert quarter["validated_by_user_id"] == "qa-1"

    untouched, untouched_meta = validate_paginated(
        api.list_data_batches(qa_headers, params={"monitor_id": data_env.monitor_id, "year": 2024})
    )
    assert untouched_meta["total_count"] == 4
    for quarter in untouched:
        assert_batch_dimensions(quarter, "VALIDATED", "UNSUBMITTED")

    package = get_success_data(api.get_package(data_env.package_id, pm_headers))
    assert package["included_batch_count"] == 4
    assert package["certification_ready"] is True


def test_qc_pass_resets_the_failure_counter_and_allows_return_to_service(
    api, monitor_env, tech_headers, pm_headers
):
    """A passing check clears the failure run and unblocks the return to service.

    PRD §3.3: "For a span check, take the absolute value of `span_drift_pct`, round it to two decimal places, and compare it against the governing method's `max_span_drift_pct`: an absolute drift at or below the tolerance is `PASS`, a drift above the tolerance but at or below one and a half times the tolerance is `WARN`, and anything beyond that is `FAIL`."
    PRD §3.3: "Third, an instrument that is `OPERATING` when it records a `FAIL` is automatically driven `OPERATING → OUT_OF_SERVICE` in the same request, with `out_of_service_since` stamped from the logical clock and the site's `operating_monitor_count` decremented — the instrument is pulled from service without anyone asking."
    PRD §3.3: "On a `FAIL` outcome no timestamp moves at all."
    PRD §3.3: "Second, `consecutive_qc_failure_count` increments by 1 on a `FAIL` and resets to 0 on a `PASS` or a `WARN`; it counts the run of failures since the last non-failing event."
    PRD §3.3: "Supplying `new_status` as `OPERATING` advances `OUT_OF_SERVICE → OPERATING` and imposes two extra conditions: `consecutive_qc_failure_count` must be 0, meaning a passing or warning activity has been logged since the last failure, and the instrument's site must itself be `OPERATING`."
    PRD §3.3: "Returning to service closes out the accrual: `out_of_service_day_count` grows by the number of whole days elapsed from `out_of_service_since` to the logical clock, computed by dividing the elapsed seconds by 86400 and discarding any fraction, and `out_of_service_since` is cleared to null."
    PRD §3.3: "An elapsed-days figure no greater than the interval yields `QC_CURRENT`; an elapsed figure greater than the interval but no greater than the interval plus a grace period of one week yields `QC_DUE`; anything beyond that yields `QC_DELINQUENT`."

    Design: Corner/state_machines/qc_pass_resets_the_failure_counter_and_allows_return_to_service
    """
    failed = validate_success(
        api.create_qc_event(
            monitor_env.monitor_id,
            span_check_payload(performed_at=CANONICAL_CLOCK, span_drift_pct=9.0),
            tech_headers,
        ),
        201,
    )
    assert failed["outcome"] == "FAIL"

    parked = get_success_data(api.get_monitor(monitor_env.monitor_id, pm_headers))
    assert parked["monitor_status"] == "OUT_OF_SERVICE"
    assert _instant(parked["out_of_service_since"]) == _instant(CANONICAL_CLOCK)
    assert parked["consecutive_qc_failure_count"] == 1
    assert _instant(parked["last_span_check_at"]) == _instant("2026-01-02T00:00:00Z")

    set_clock(api, "2026-01-20T00:00:00Z")
    passed = validate_success(
        api.create_qc_event(
            monitor_env.monitor_id,
            span_check_payload(performed_at="2026-01-20T00:00:00Z", span_drift_pct=2.0),
            tech_headers,
        ),
        201,
    )
    assert passed["outcome"] == "PASS"

    recovered = get_success_data(api.get_monitor(monitor_env.monitor_id, pm_headers))
    assert recovered["consecutive_qc_failure_count"] == 0
    assert _instant(recovered["last_span_check_at"]) == _instant("2026-01-20T00:00:00Z")

    returned = validate_success(
        api.set_service_status(
            monitor_env.monitor_id,
            {"new_status": "OPERATING", "reason": "Analyser repaired and verified"},
            tech_headers,
        )
    )
    assert returned["monitor_status"] == "OPERATING"
    assert returned["out_of_service_day_count"] == 15
    assert returned["out_of_service_since"] is None
    assert returned["qc_posture"] == "QC_CURRENT"
    assert returned["qc_posture_in_service"] == "QC_CURRENT"

    site = get_success_data(api.get_site(monitor_env.site_id, pm_headers))
    assert site["operating_monitor_count"] == 1

    network = get_success_data(api.get_network(monitor_env.network_id, pm_headers))
    assert network["delinquent_monitor_count"] == 0


def test_failing_span_check_parks_the_monitor_only_when_the_outcome_is_fail(
    api, monitor_env, tech_headers, pm_headers
):
    """The automatic removal from service follows the graded outcome, not the logging.

    PRD §3.3: "For a span check, take the absolute value of `span_drift_pct`, round it to two decimal places, and compare it against the governing method's `max_span_drift_pct`: an absolute drift at or below the tolerance is `PASS`, a drift above the tolerance but at or below one and a half times the tolerance is `WARN`, and anything beyond that is `FAIL`."
    PRD §3.3: "Both comparisons at the limit are inclusive: an absolute reading exactly equal to the tolerance is `PASS`, not `WARN`, and a reading exactly equal to one and a half times the tolerance is `WARN`, not `FAIL`."
    PRD §3.3: "First, when the outcome is `PASS` or `WARN`, the timestamp on the instrument that corresponds to the activity type advances to the request's `performed_at` — a calibration refreshes `last_calibration_at`, a span check refreshes `last_span_check_at`, a zero check refreshes `last_zero_check_at`, a preventive-maintenance activity refreshes `last_maintenance_at`."
    PRD §3.3: "On a `FAIL` outcome no timestamp moves at all."
    PRD §3.3: "Third, an instrument that is `OPERATING` when it records a `FAIL` is automatically driven `OPERATING → OUT_OF_SERVICE` in the same request, with `out_of_service_since` stamped from the logical clock and the site's `operating_monitor_count` decremented — the instrument is pulled from service without anyone asking."

    Design: Corner/state_machines/failing_span_check_parks_the_monitor_only_when_the_outcome_is_fail
    """
    warned = validate_success(
        api.create_qc_event(
            monitor_env.monitor_id,
            span_check_payload(performed_at="2026-01-03T00:00:00Z", span_drift_pct=7.5),
            tech_headers,
        ),
        201,
    )
    assert warned["outcome"] == "WARN"

    still_operating = get_success_data(api.get_monitor(monitor_env.monitor_id, pm_headers))
    assert still_operating["monitor_status"] == "OPERATING"
    assert still_operating["consecutive_qc_failure_count"] == 0
    assert _instant(still_operating["last_span_check_at"]) == _instant("2026-01-03T00:00:00Z")
    assert still_operating["out_of_service_since"] is None

    failed = validate_success(
        api.create_qc_event(
            monitor_env.monitor_id,
            span_check_payload(performed_at="2026-01-04T00:00:00Z", span_drift_pct=7.51),
            tech_headers,
        ),
        201,
    )
    assert failed["outcome"] == "FAIL"

    parked = get_success_data(api.get_monitor(monitor_env.monitor_id, pm_headers))
    assert parked["monitor_status"] == "OUT_OF_SERVICE"
    assert _instant(parked["out_of_service_since"]) == _instant(CANONICAL_CLOCK)
    assert parked["consecutive_qc_failure_count"] == 1
    assert _instant(parked["last_span_check_at"]) == _instant("2026-01-03T00:00:00Z")

    site = get_success_data(api.get_site(monitor_env.site_id, pm_headers))
    assert site["operating_monitor_count"] == 0


def test_site_operating_monitor_count_reconciles_with_service_status_changes(
    api, monitor_env, tech_headers, pm_headers
):
    """The site's roster counter tracks the operating instruments in both directions.

    PRD §3.2: "`operating_monitor_count` is the number of instruments at the site whose lifecycle status is `OPERATING`."
    PRD §3.3: "On success the site's `operating_monitor_count` increments by 1, both the instrument's and the site's `version` increment, and the instrument becomes visible to the primary-monitor selector described in §3.7."
    PRD §3.3: "Supplying `new_status` as `OUT_OF_SERVICE` advances `OPERATING → OUT_OF_SERVICE`, stamps `out_of_service_since` from the logical clock, and decrements the site's `operating_monitor_count` by 1; no additional condition applies beyond the from-state."
    PRD §3.3: "Returning to service closes out the accrual: `out_of_service_day_count` grows by the number of whole days elapsed from `out_of_service_since` to the logical clock, computed by dividing the elapsed seconds by 86400 and discarding any fraction, and `out_of_service_since` is cleared to null."

    Design: Corner/state_machines/site_operating_monitor_count_reconciles_with_service_status_changes
    """
    first = get_success_data(api.get_site(monitor_env.site_id, pm_headers))
    assert first["operating_monitor_count"] == 1

    second_monitor = create_operating_monitor(
        api,
        monitor_env.site_id,
        monitor_env.method_id,
        poc=2,
        is_primary_for_design_value=False,
    )
    assert second_monitor["monitor_status"] == "OPERATING"

    both = get_success_data(api.get_site(monitor_env.site_id, pm_headers))
    assert both["operating_monitor_count"] == 2

    parked = validate_success(
        api.set_service_status(
            second_monitor["id"],
            {"new_status": "OUT_OF_SERVICE", "reason": "Pump replacement"},
            tech_headers,
        )
    )
    assert parked["monitor_status"] == "OUT_OF_SERVICE"
    assert _instant(parked["out_of_service_since"]) == _instant(CANONICAL_CLOCK)

    one_parked = get_success_data(api.get_site(monitor_env.site_id, pm_headers))
    assert one_parked["operating_monitor_count"] == 1

    returned = validate_success(
        api.set_service_status(
            second_monitor["id"], {"new_status": "OPERATING", "reason": "Pump replaced"}, tech_headers
        )
    )
    assert returned["monitor_status"] == "OPERATING"
    assert returned["out_of_service_since"] is None
    # The logical clock never moved, so no whole day of out-of-service time accrued.
    assert returned["out_of_service_day_count"] == 0

    restored = get_success_data(api.get_site(monitor_env.site_id, pm_headers))
    assert restored["operating_monitor_count"] == 2

    rows, meta = validate_paginated(
        api.list_monitors(
            pm_headers, params={"site_id": monitor_env.site_id, "monitor_status": "OPERATING"}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_network_assessment_submit_flips_the_network_into_under_assessment(
    api, monitor_env, pm_headers
):
    """Submitting the cycle rescores it and moves the network under assessment.

    PRD §3.9: "`submitted_at` is stamped from the logical clock."
    PRD §3.9: "The submission also reaches the network itself: `network_status` becomes `UNDER_ASSESSMENT` and `current_assessment_year` becomes the assessment's `cycle_year`, and both rows' `version` counters increment."
    PRD §3.9: "The first step converts the network's `metropolitan_population` into `required_population_site_count`, the number of population-oriented sites the network owes: a population below five hundred thousand requires 1, a population from five hundred thousand up to but not including one million requires 2, a population from one million up to but not including two and a half million requires 3, and a population of two and a half million or more requires 4."
    PRD §3.9: "The three credits are summed and divided by the requirement total — `required_population_site_count` plus one required source site plus one required background site — and `coverage_ratio` is that quotient rounded to four decimal places."
    PRD §3.9: "`adequacy_score` is `coverage_ratio` multiplied by the quality-control factor, multiplied by the siting factor, multiplied by 100, and rounded to one decimal place."
    PRD §3.9: "The fourth step bands the result into `adequacy_tier`: a score of 90.0 or above is `ADEQUATE`, a score below 90.0 but at or above 75.0 is `CONDITIONAL`, and anything below 75.0 is `INADEQUATE`."
    PRD §3.9: "`APPROVE` advances `SUBMITTED → APPROVED`, stamps `approved_at` from the logical clock and `approved_by_user_id` from the calling `X-User-ID`, and — critically — makes every change request citing this assessment eligible for approval."

    Design: Corner/state_machines/network_assessment_submit_flips_the_network_into_under_assessment
    """
    assessment = validate_success(
        api.create_assessment(assessment_payload(monitor_env.network_id, 2026), pm_headers), 201
    )

    submitted = validate_success(
        api.submit_assessment(
            assessment["id"], {"submission_note": "Five-year assessment submitted"}, pm_headers
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert _instant(submitted["submitted_at"]) == _instant(CANONICAL_CLOCK)
    assert submitted["approved_at"] is None
    # A metropolitan population of 1,200,000 owes three population-oriented sites.
    assert submitted["required_population_site_count"] == 3
    # One operating population-oriented site over a requirement total of 3 + 1 + 1.
    assert_ratio_4dp(submitted["coverage_ratio"], 0.2)
    assert_pct(submitted["adequacy_score"], 20.0)
    assert submitted["adequacy_tier"] == "INADEQUATE"

    network = get_success_data(api.get_network(monitor_env.network_id, pm_headers))
    assert network["network_status"] == "UNDER_ASSESSMENT"
    assert network["current_assessment_year"] == 2026


def test_assessment_return_decision_cycles_the_submitted_row_back_to_draft(
    api, monitor_env, pm_headers, epa_headers
):
    """A returned cycle re-enters draft on the same row and can be resubmitted.

    PRD §3.9: "`RETURN` advances `SUBMITTED → DRAFT` and increments `return_count` by 1; a returned assessment goes back to draft rather than to any distinct returned state, so the `DRAFT → SUBMITTED → DRAFT` cycle can be traversed repeatedly."
    PRD §3.9: "Under **either** decision the network's `network_status` returns to `ACTIVE`, and under either decision both the assessment's and the network's `version` counters increment."
    PRD §3.9: "`APPROVE` advances `SUBMITTED → APPROVED`, stamps `approved_at` from the logical clock and `approved_by_user_id` from the calling `X-User-ID`, and — critically — makes every change request citing this assessment eligible for approval."
    PRD §3.9: "Scoring is re-run from the network's present census immediately before submission, refreshing `required_population_site_count`, `coverage_ratio`, `adequacy_score` and `adequacy_tier`, so a site that came into operation between opening and submitting is credited."
    PRD §3.9: "The submission also reaches the network itself: `network_status` becomes `UNDER_ASSESSMENT` and `current_assessment_year` becomes the assessment's `cycle_year`, and both rows' `version` counters increment."

    Design: Corner/state_machines/assessment_return_decision_cycles_the_submitted_row_back_to_draft
    """
    assessment = validate_success(
        api.create_assessment(assessment_payload(monitor_env.network_id, 2026), pm_headers), 201
    )
    validate_success(api.submit_assessment(assessment["id"], {}, pm_headers))

    returned = validate_success(
        api.decide_assessment(
            assessment["id"],
            {"decision": "RETURN", "decision_note": "Add the source-oriented site rationale"},
            epa_headers,
        )
    )
    assert returned["status"] == "DRAFT"
    assert returned["return_count"] == 1
    assert returned["approved_at"] is None
    assert returned["approved_by_user_id"] is None

    between = get_success_data(api.get_network(monitor_env.network_id, pm_headers))
    assert between["network_status"] == "ACTIVE"
    assert between["current_assessment_year"] == 2026

    resubmitted = validate_success(
        api.submit_assessment(assessment["id"], {"submission_note": "Rationale added"}, pm_headers)
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["return_count"] == 1
    assert_pct(resubmitted["adequacy_score"], 20.0)

    network = get_success_data(api.get_network(monitor_env.network_id, pm_headers))
    assert network["network_status"] == "UNDER_ASSESSMENT"


def test_data_batch_reopen_cycles_a_validated_quarter_back_through_validation(
    api, monitor_env, qa_headers
):
    """The same quarter travels the reopen loop without leaving the validation dimension.

    PRD §3.5: "Reopening a validated quarter advances `VALIDATED → REOPENED` and requires a `reopen_reason`."
    PRD §3.5: "A permitted reopen increments `reopen_count` by 1, clears `validated_by_user_id` to null, leaves `submission_status` untouched, and increments the quarter's `version`."
    PRD §3.5: "Opening a quarter for review advances either `RAW → IN_VALIDATION` or `REOPENED → IN_VALIDATION`."
    PRD §3.5: "On success `validated_by_user_id` is set to the calling `X-User-ID`, hour accounting is re-run so `completeness_pct` and `regulatory_use_eligible` are refreshed, every certification package that selects this quarter re-runs its rollup, `submission_status` is left exactly where it was because the two dimensions are independent, and the quarter's `version` increments."
    PRD §3.4: "Seventh, `regulatory_use_eligible` is true exactly when that *rounded* `completeness_pct` is greater than or equal to the pollutant's `completeness_threshold_pct`; the comparison is inclusive at the threshold, and it uses the rounded figure and never the raw ratio."

    Design: Corner/state_machines/data_batch_reopen_cycles_a_validated_quarter_back_through_validation
    """
    batch = validate_success(
        api.create_data_batch(data_batch_payload(monitor_env.monitor_id, 2025, 1), qa_headers), 201
    )
    validate_success(api.begin_validation(batch["id"], {}, qa_headers))
    first_pass = validate_success(
        api.validate_batch(batch["id"], {"validation_note": "First pass"}, qa_headers)
    )
    assert_batch_dimensions(first_pass, "VALIDATED", "UNSUBMITTED")
    assert first_pass["validated_by_user_id"] == "qa-1"

    reopened = validate_success(
        api.reopen_batch(
            batch["id"], {"reopen_reason": "Analyser audit found a flow error"}, qa_headers
        )
    )
    assert_batch_dimensions(reopened, "REOPENED", "UNSUBMITTED")
    assert reopened["reopen_count"] == 1
    assert reopened["validated_by_user_id"] is None
    assert_pct(reopened["completeness_pct"], 100.0)
    assert reopened["regulatory_use_eligible"] is True

    under_review = validate_success(api.begin_validation(batch["id"], {}, qa_headers))
    assert under_review["validation_status"] == "IN_VALIDATION"

    second_pass = validate_success(
        api.validate_batch(
            batch["id"], {"validation_note": "Second pass after audit"}, qa_headers
        )
    )
    assert_batch_dimensions(second_pass, "VALIDATED", "UNSUBMITTED")
    assert second_pass["validated_by_user_id"] == "qa-1"
    assert second_pass["reopen_count"] == 1
    assert_pct(second_pass["completeness_pct"], 100.0)
    assert second_pass["regulatory_use_eligible"] is True


def test_second_design_value_for_the_same_key_supersedes_the_prior_provisional_row(
    api, monitor_env, pm_headers
):
    """Recomputing the same key retires the earlier provisional row as recomputed.

    PRD §3.7: "A completed computation is stored with `status` `PROVISIONAL`."
    PRD §3.7: "Any earlier design value for the same site, pollutant, `period_end_year` and `variant` that was still `PROVISIONAL` moves to `SUPERSEDED` with `stale_reason` set to `RECOMPUTED` and its `version` incremented; the referenced site's `version` increments by 1 and its `current_attainment_status` is refreshed."
    PRD §3.7: "`stale_reason` is null unless the row is superseded, and takes one of `EVENT_EXCLUSION_APPLIED`, `BATCH_REVALIDATED` or `RECOMPUTED` depending on which of the three paths of §3.5, §3.6 or this subsection retired the row."
    PRD §3.7: "Otherwise the candidates are ordered by `poc` ascending and, where two share a `poc`, by `created_at` ascending; the first is recorded as `primary_monitor_id`."
    PRD §3.7: "When no year is complete the array is empty."
    PRD §3.7: "If `complete_year_count` does not equal the pollutant's `design_value_years`, `design_value` is null and `attainment_status` is `INSUFFICIENT_DATA`."
    PRD §2.7: "A successful computation increments the site's `version`."

    Design: Corner/state_machines/second_design_value_for_the_same_key_supersedes_the_prior_provisional_row
    """
    first_version = monitor_env.site_version()
    first = validate_success(
        api.create_design_value(
            design_value_payload(
                monitor_env.site_id,
                monitor_env.pollutant_id,
                2025,
                "WITH_EVENT_DATA",
                first_version,
            ),
            pm_headers,
        ),
        201,
    )
    assert first["status"] == "PROVISIONAL"

    second_version = monitor_env.site_version()
    assert second_version == first_version + 1

    second = validate_success(
        api.create_design_value(
            design_value_payload(
                monitor_env.site_id,
                monitor_env.pollutant_id,
                2025,
                "WITH_EVENT_DATA",
                second_version,
            ),
            pm_headers,
        ),
        201,
    )
    assert second["status"] == "PROVISIONAL"
    assert second["stale_reason"] is None

    superseded = get_success_data(api.get_design_value(first["id"], pm_headers))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["stale_reason"] == "RECOMPUTED"

    for row in (superseded, second):
        assert row["primary_monitor_id"] == monitor_env.monitor_id
        assert row["complete_year_count"] == 0
        assert_annual_statistics(row["annual_statistics"], [])
        assert row["design_value"] is None
        assert row["attainment_status"] == "INSUFFICIENT_DATA"

    site = get_success_data(api.get_site(monitor_env.site_id, pm_headers))
    assert site["current_attainment_status"] == "INSUFFICIENT_DATA"
    assert site["version"] == second_version + 1

    rows, meta = validate_paginated(
        api.list_design_values(
            pm_headers, params={"site_id": monitor_env.site_id, "status": "PROVISIONAL"}
        )
    )
    assert meta["total_count"] == 1
    assert find_by_id(rows, second["id"]) is not None
