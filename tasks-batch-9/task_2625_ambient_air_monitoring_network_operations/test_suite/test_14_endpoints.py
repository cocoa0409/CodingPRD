"""Endpoint-level behaviour: listings, action endpoints and computed reads.

Every test builds its own world from an empty database through PRD-declared
endpoints only, then exercises one endpoint contract from PRD 3 and 4.
"""

from test_helpers import (
    ADMIN_HEADERS,
    EPA_HEADERS,
    PM_HEADERS,
    QA_HEADERS,
    TECH_HEADERS,
    ERR_INVALID_STATE,
    approve_monitor,
    approve_siting,
    approved_assessment,
    base_environment,
    bulk_ingest_payload,
    canonical_environment,
    commence_operations,
    create_monitor,
    create_site,
    assert_batch_dimensions,
    assert_hour_budget_conserved,
    assert_immutable_record,
    assert_millisecond_timestamp,
    assert_pct,
    assert_site_census_partitioned,
    assert_versioned_record,
    get_success_data,
    ingest_worked_example_quarters,
    network_payload,
    open_package,
    operating_site_environment,
    pollutant_payload,
    set_clock,
    submitted_change_request,
    twelve_validated_quarters,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-01-05T00:00:00Z"


def assert_instant(actual, expected):
    """Compare a server instant against an expected UTC instant.

    The comparison ignores the optional fractional-second digits so that a
    value written as 2026-01-05T00:00:00.000Z matches 2026-01-05T00:00:00Z.
    """
    assert type(actual) is str, f"expected an instant string, got {actual!r}"
    assert actual.endswith("Z"), f"expected a UTC instant, got {actual!r}"
    assert actual[:19] == expected[:19], f"expected {expected}, got {actual}"


def test_site_listing_combines_filters_with_pagination(api):
    """Filters, ordering and the pagination window on the site listing.

    Three sites of one network are created at three distinct logical-clock
    instants, so the declared ordering is unambiguous, and each filter narrows
    the same population while total_count keeps reporting the filtered rows.

    PRD 2.3: "Unless a specific endpoint's description states another order, list results are sorted by `created_at` ascending."
    PRD 2.3: "For list responses, the `meta` object carries `limit` and `offset` as applied, `total_count` as the number of rows matching the filter before the page window is taken, and `has_more` as a boolean that is true when rows remain beyond the current window."

    Design: Corner/endpoints/site_listing_combines_filters_with_pagination
    """
    env = base_environment(api)

    site_a = create_site(api, env.network_id, site_code="S-001", site_type="POPULATION_ORIENTED")
    approve_siting(api, site_a["id"])
    commence_operations(api, site_a["id"])

    set_clock(api, "2026-01-06T00:00:00Z")
    site_b = create_site(
        api,
        env.network_id,
        site_code="S-002",
        site_type="BACKGROUND",
        latitude=40.10,
        longitude=-105.30,
        population_served=0,
        distance_to_roadway_m=150.0,
    )

    set_clock(api, "2026-01-07T00:00:00Z")
    site_c = create_site(
        api,
        env.network_id,
        site_code="S-003",
        site_type="SOURCE_ORIENTED",
        latitude=39.60,
        longitude=-104.80,
        population_served=12000,
        distance_to_roadway_m=40.0,
        distance_to_source_m=300.0,
    )
    approve_siting(api, site_c["id"])

    rows, meta = validate_paginated(
        api.list_sites(PM_HEADERS, {"network_id": env.network_id})
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [site_a["id"], site_b["id"], site_c["id"]]

    rows, meta = validate_paginated(
        api.list_sites(PM_HEADERS, {"network_id": env.network_id, "status": "PROPOSED"})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [site_b["id"]]

    rows, meta = validate_paginated(
        api.list_sites(
            PM_HEADERS, {"network_id": env.network_id, "site_type": "SOURCE_ORIENTED"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [site_c["id"]]

    rows, meta = validate_paginated(
        api.list_sites(PM_HEADERS, {"network_id": env.network_id, "limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert [row["id"] for row in rows] == [site_a["id"], site_b["id"]]

    rows, meta = validate_paginated(
        api.list_sites(PM_HEADERS, {"network_id": env.network_id, "limit": 2, "offset": 2})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert rows[0]["id"] == site_c["id"]


def test_commission_applies_every_declared_side_effect(api):
    """Commissioning writes the instrument, the site's counter and both versions.

    PRD 3.3: "Commissioning is the `FieldTechnician`'s act and advances `APPROVED → OPERATING`, optionally with a `commission_note`."
    PRD 3.3: "On success the site's `operating_monitor_count` increments by 1, both the instrument's and the site's `version` increment, and the instrument becomes visible to the primary-monitor selector described in §3.7."

    Design: Corner/endpoints/commission_applies_every_declared_side_effect
    """
    env = operating_site_environment(api)
    monitor = create_monitor(api, env.site_id, env.method_id)
    approve_monitor(api, monitor["id"])

    monitor_before = get_success_data(api.get_monitor(monitor["id"], TECH_HEADERS))
    site_before = get_success_data(api.get_site(env.site_id, TECH_HEADERS))
    assert monitor_before["monitor_status"] == "APPROVED"
    assert site_before["operating_monitor_count"] == 0

    commissioned = validate_success(
        api.commission_monitor(
            monitor["id"], {"commission_note": "Instrument accepted into service"}, TECH_HEADERS
        ),
        200,
    )
    assert_versioned_record(commissioned)
    assert commissioned["monitor_status"] == "OPERATING"
    assert commissioned["version"] == monitor_before["version"] + 1
    assert commissioned["out_of_service_since"] is None
    # The instrument was installed on 2022-12-20 and has never had a passing
    # span check, so the calendar baseline is installed_at and the elapsed
    # figure is far beyond the 14-day interval plus its one-week grace.
    assert commissioned["qc_posture"] == "QC_DELINQUENT"
    assert commissioned["qc_posture_in_service"] == "QC_DELINQUENT"

    site_after = get_success_data(api.get_site(env.site_id, TECH_HEADERS))
    assert site_after["operating_monitor_count"] == 1
    assert site_after["version"] == site_before["version"] + 1


def test_the_clock_endpoint_sets_the_logical_now_for_later_writes(api):
    """Rows minted after two clock settings carry the two logical instants.

    PRD 2.5: "A `NetworkAdmin` may move the clock by supplying a `to_iso8601` instant, and that instant becomes the clock for every subsequent request."
    PRD 2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at the moment the row was created."
    PRD 2.5: "The clock-setting capability returns no resource payload; its `data` is an empty object."

    Design: Corner/endpoints/the_clock_endpoint_sets_the_logical_now_for_later_writes
    """
    first = validate_success(api.set_clock({"to_iso8601": CLOCK}, ADMIN_HEADERS), 200)
    assert first == {}

    pollutant = validate_success(
        api.create_pollutant(pollutant_payload(), ADMIN_HEADERS), 201
    )
    assert_immutable_record(pollutant)
    assert_millisecond_timestamp(pollutant["created_at"])
    assert_instant(pollutant["created_at"], CLOCK)

    second = validate_success(
        api.set_clock({"to_iso8601": "2026-02-01T12:30:00Z"}, ADMIN_HEADERS), 200
    )
    assert second == {}

    network = validate_success(
        api.create_network(
            network_payload(
                name="Later Network", agency_code="AQ04", metropolitan_population=100000
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_versioned_record(network)
    assert_instant(network["created_at"], "2026-02-01T12:30:00Z")
    assert_instant(network["updated_at"], "2026-02-01T12:30:00Z")


def test_bulk_ingest_persists_every_item_in_request_order(api):
    """Twelve quarters reported in one call, each already accounted for.

    PRD 3.4: "Reporting many quarters for one instrument in a single call is also supported, and it is strictly transactional."
    PRD 3.4: "Hour accounting runs once per created quarter."
    PRD 3.4: "A quarter is born with `validation_status` `RAW` and `submission_status` `UNSUBMITTED`, with `reopen_count` at 0 and `invalidation_applied_by_user_ids` an empty list."

    Design: Corner/endpoints/bulk_ingest_persists_every_item_in_request_order
    """
    env = canonical_environment(api)

    rows = validate_success(
        api.bulk_ingest(bulk_ingest_payload(env.monitor_id), QA_HEADERS), 201
    )
    assert len(rows) == 12
    assert (rows[0]["year"], rows[0]["quarter"]) == (2023, 1)
    assert (rows[11]["year"], rows[11]["quarter"]) == (2025, 4)

    first = rows[0]
    assert first["scheduled_hour_count"] == 2160
    assert first["adjusted_scheduled_hour_count"] == 2160
    assert first["valid_hour_count"] == 2160
    assert first["invalidated_hour_count"] == 0
    assert first["excused_hour_count"] == 0
    assert first["event_excluded_hour_count"] == 0
    assert_pct(first["completeness_pct"], 100.0)
    assert first["regulatory_use_eligible"] is True
    assert_hour_budget_conserved(first)

    for row in rows:
        assert_batch_dimensions(row, "RAW", "UNSUBMITTED")
        assert row["reopen_count"] == 0
        assert row["invalidation_applied_by_user_ids"] == []

    listed, meta = validate_paginated(
        api.list_data_batches(QA_HEADERS, {"monitor_id": env.monitor_id, "limit": 100})
    )
    assert meta["total_count"] == 12
    assert len(listed) == 12


def test_bulk_validate_only_touches_raw_rows_in_the_selected_year(api):
    """A year-narrowed bulk validation moves the four quarters of that year only.

    PRD 3.5: "The request names `monitor_id` and may narrow the selection with an optional `year`."
    PRD 3.5: "The response lists only the quarters actually transitioned, ordered by `year` and then `quarter`."

    Design: Corner/endpoints/bulk_validate_only_touches_raw_rows_in_the_selected_year
    """
    env = canonical_environment(api)
    ingest_worked_example_quarters(env)

    rows = validate_success(
        api.bulk_validate({"monitor_id": env.monitor_id, "year": 2024}, QA_HEADERS), 200
    )
    assert len(rows) == 4
    assert [(row["year"], row["quarter"]) for row in rows] == [
        (2024, 1),
        (2024, 2),
        (2024, 3),
        (2024, 4),
    ]
    for row in rows:
        assert_batch_dimensions(row, "VALIDATED", "UNSUBMITTED")
        assert row["validated_by_user_id"] == "qa-1"

    _, meta = validate_paginated(
        api.list_data_batches(
            QA_HEADERS,
            {"monitor_id": env.monitor_id, "validation_status": "VALIDATED", "limit": 100},
        )
    )
    assert meta["total_count"] == 4

    _, meta = validate_paginated(
        api.list_data_batches(
            QA_HEADERS,
            {"monitor_id": env.monitor_id, "validation_status": "RAW", "limit": 100},
        )
    )
    assert meta["total_count"] == 8


def test_relocation_approval_links_the_replacement_site_back_to_the_old_one(api):
    """An approved relocation writes the back-link onto the successor site.

    The retiring site ends in its terminal state with its instrument written
    off, while the successor keeps its own approved standing and becomes
    discoverable through the listing filter on the site it replaces.

    PRD 3.9: "The second hop sets `replaces_site_id` on the nominated replacement site to the retiring site's identifier, incrementing the replacement site's `version` as well as the retiring site's."
    PRD 3.2: "A site that arrived at its position through a relocation carries `replaces_site_id` pointing at the site it took over from; the field is null on every site that has not replaced another."

    Design: Corner/endpoints/relocation_approval_links_the_replacement_site_back_to_the_old_one
    """
    env = canonical_environment(api)
    replacement = create_site(
        api,
        env.network_id,
        site_code="S-009",
        latitude=39.76,
        longitude=-104.97,
    )
    approve_siting(api, replacement["id"])

    approved_assessment(env)
    request = submitted_change_request(
        env, request_type="RELOCATION", replacement_site_id=replacement["id"]
    )

    decided = validate_success(
        api.decide_change_request(
            request["id"], {"decision": "APPROVE", "decision_note": "Relocation approved"}, EPA_HEADERS
        ),
        200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == "epa-1"
    assert_instant(decided["effective_at"], CLOCK)

    retiring = get_success_data(api.get_site(env.site_id, PM_HEADERS))
    assert retiring["status"] == "RELOCATED"
    assert retiring["replaces_site_id"] is None

    successor = get_success_data(api.get_site(replacement["id"], PM_HEADERS))
    assert successor["replaces_site_id"] == env.site_id
    assert successor["status"] == "SITING_APPROVED"

    rows, meta = validate_paginated(
        api.list_sites(PM_HEADERS, {"replaces_site_id": env.site_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == replacement["id"]

    monitor = get_success_data(api.get_monitor(env.monitor_id, TECH_HEADERS))
    assert monitor["monitor_status"] == "DECOMMISSIONED"

    network = env.read_network()
    assert network["total_site_count"] == 2
    assert network["operating_site_count"] == 0
    assert network["relocated_site_count"] == 1
    assert network["approved_site_count"] == 1
    assert_site_census_partitioned(network)


def test_package_read_returns_the_recomputed_rollup(api):
    """A 2024 package summarises only the four quarters of its own year.

    PRD 3.8: "The selection walks the graph rather than storing a membership list: a quarter is selected when its instrument's site belongs to the package's network, when the pollutant of that instrument's reference method is the package's pollutant, when the quarter's `year` equals the package's `year`, and when the quarter's `validation_status` is `VALIDATED`."
    PRD 3.8: "First, `certification_deadline` is pinned to the first of May of the year following `year`, at midnight UTC."

    Design: Corner/endpoints/package_read_returns_the_recomputed_rollup
    """
    env = twelve_validated_quarters(api)
    package = open_package(env, year=2024)

    read = validate_success(api.get_package(package["id"], EPA_HEADERS), 200)
    assert read["id"] == package["id"]
    assert read["included_batch_count"] == 4
    assert read["eligible_batch_count"] == 4
    assert_pct(read["rollup_completeness_pct"], 100.0)
    assert read["certification_ready"] is True
    assert_instant(read["certification_deadline"], "2025-05-01T00:00:00Z")
    assert read["status"] == "DRAFT"
    assert read["rejection_count"] == 0

    _, meta = validate_paginated(
        api.list_network_certification_packages(env.network_id, PM_HEADERS, {"year": 2024})
    )
    assert meta["total_count"] == 1


def test_reinstating_a_site_that_is_not_suspended_is_rejected(api):
    """Reinstatement of an operating site is refused and changes nothing.

    PRD 3.2: "A `ProgramManager` reinstates a suspended site, advancing `SUSPENDED → OPERATING` with an optional `reinstatement_note`; `suspended_at`, which held the instant the site entered suspension, is cleared to null."
    PRD 2.11: "After concurrency come the state checks — the target's own from-state and the cross-row preconditions its transition declares (`ERR_INVALID_STATE`), whether the target is already terminal (`ERR_ALREADY_TERMINAL`), and the specific state guards for certified quarters (`ERR_BATCH_CERTIFIED`), non-operating sites (`ERR_SITE_NOT_OPERATING`) and unvalidated member quarters (`ERR_MEMBER_BATCH_NOT_VALIDATED`)."

    Design: Corner/endpoints/reinstating_a_site_that_is_not_suspended_is_rejected
    """
    env = canonical_environment(api)
    site_before = env.read_site()
    assert site_before["status"] == "OPERATING"

    validate_error(
        api.reinstate_site(
            env.site_id, {"reinstatement_note": "Return to service"}, PM_HEADERS
        ),
        ERR_INVALID_STATE,
        409,
    )

    site_after = env.read_site()
    assert site_after["status"] == "OPERATING"
    assert site_after["suspended_at"] is None
    assert site_after["version"] == site_before["version"]

    network = env.read_network()
    assert network["operating_site_count"] == 1
    assert network["suspended_site_count"] == 0
    assert_site_census_partitioned(network)
