"""Role-based access control and the two segregation-of-duties rules.

The role checks exercise every allowed hop of the network standup chain and the
refusals each role earns outside its own remit; the last two tests prove that
the duty bars compare operator identifiers rather than role names.
"""

from test_helpers import (
    ADMIN_HEADERS,
    BAD_ROLE_HEADERS,
    EPA_HEADERS,
    PM_HEADERS,
    QA_HEADERS,
    QA2_HEADERS,
    ROLE_ONLY_HEADERS,
    ROLE_PROGRAM_MANAGER,
    ROLE_QA_OFFICER,
    TECH_HEADERS,
    USER_ONLY_HEADERS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    approve_monitor,
    assert_pct,
    canonical_environment,
    create_monitor,
    create_site,
    data_batch_payload,
    get_success_data,
    headers_for,
    ingest_worked_example_quarters,
    invalidation_payload,
    monitor_payload,
    network_payload,
    operating_site_environment,
    package_payload,
    pollutant_payload,
    reference_method_payload,
    set_clock,
    site_payload,
    span_check_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-01-05T00:00:00Z"


def test_each_role_can_run_its_own_exclusive_operations(api):
    """The whole standup chain succeeds when each hop is called by its owner.

    PRD 2.1: "A `NetworkAdmin` is the state air programme's configuration officer."
    PRD 2.1: "A `FieldTechnician` performs field operations: commissioning approved instruments, logging calibration, span, zero, precision and preventive-maintenance activity, and taking instruments out of and back into service."
    PRD 2.1: "A `QaOfficer` is the quality-assurance officer who ingests monitor-quarters, invalidates and restores hour ranges, and decides each quarter's validation outcome."
    PRD 2.1: "An `EpaRegionalReviewer` is the federal regional reviewer who holds every approval gate the state cannot self-grant — method designation changes, site siting approval, instrument approval, exceptional-event concurrence, design-value finalization, certification rejection, assessment decisions and network-change decisions."

    Design: Corner/rbac/each_role_can_run_its_own_exclusive_operations
    """
    set_clock(api, CLOCK)

    pollutant = validate_success(api.create_pollutant(pollutant_payload(), ADMIN_HEADERS), 201)
    method = validate_success(
        api.create_reference_method(reference_method_payload(pollutant["id"]), ADMIN_HEADERS), 201
    )
    network = validate_success(api.create_network(network_payload(), ADMIN_HEADERS), 201)
    site = validate_success(
        api.create_site(site_payload(network["id"]), ADMIN_HEADERS), 201
    )

    approved_site = validate_success(
        api.approve_siting(site["id"], {"waiver_granted": False}, EPA_HEADERS), 200
    )
    assert approved_site["status"] == "SITING_APPROVED"

    operating_site = validate_success(
        api.commence_operations(site["id"], {}, PM_HEADERS), 200
    )
    assert operating_site["status"] == "OPERATING"

    monitor = validate_success(
        api.create_monitor(
            monitor_payload(site["id"], method["id"], installed_at="2025-12-20T00:00:00Z"),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert validate_success(api.approve_monitor(monitor["id"], {}, EPA_HEADERS), 200)[
        "monitor_status"
    ] == "APPROVED"
    assert validate_success(api.commission_monitor(monitor["id"], {}, TECH_HEADERS), 200)[
        "monitor_status"
    ] == "OPERATING"

    event = validate_success(
        api.create_qc_event(monitor["id"], span_check_payload(), TECH_HEADERS), 201
    )
    assert event["outcome"] == "PASS"
    assert event["performed_by_user_id"] == "tech-1"

    refreshed = get_success_data(api.get_monitor(monitor["id"], TECH_HEADERS))
    assert refreshed["qc_posture"] == "QC_CURRENT"

    batch = validate_success(
        api.create_data_batch(
            data_batch_payload(
                monitor["id"], 2025, 4, scheduled_hour_count=2208, quarterly_mean_concentration=8.8
            ),
            QA_HEADERS,
        ),
        201,
    )
    assert batch["validation_status"] == "RAW"
    assert batch["submission_status"] == "UNSUBMITTED"


def test_a_regional_reviewer_cannot_run_state_agency_exclusive_operations(api):
    """The federal reviewer holds the gates but none of the state-side writes.

    PRD 2.1: "When both headers are present and well-formed but the named role is not among the roles authorised for the requested method and path, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 3.3: "Commissioning is the `FieldTechnician`'s act and advances `APPROVED → OPERATING`, optionally with a `commission_note`."
    PRD 3.8: "A `ProgramManager` opens the package by naming `network_id`, `pollutant_id` and `year`; the combination must be unique, so a network cannot hold two packages for the same pollutant and year, and `year` must be at least 2000 and at most 2100."

    Design: Corner/rbac/a_regional_reviewer_cannot_run_state_agency_exclusive_operations
    """
    env = operating_site_environment(api)
    monitor = create_monitor(api, env.site_id, env.method_id)
    approve_monitor(api, monitor["id"])

    validate_error(
        api.create_site(
            site_payload(
                env.network_id,
                site_code="S-777",
                site_type="BACKGROUND",
                latitude=40.1,
                longitude=-105.3,
                population_served=0,
                distance_to_roadway_m=150.0,
            ),
            EPA_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(api.commission_monitor(monitor["id"], {}, EPA_HEADERS), ERR_UNAUTHORIZED, 403)
    validate_error(
        api.create_data_batch(data_batch_payload(monitor["id"], 2025, 1), EPA_HEADERS),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.create_package(
            package_payload(env.network_id, env.pollutant_id, 2025), EPA_HEADERS
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    _, meta = validate_paginated(api.list_sites(PM_HEADERS, {"network_id": env.network_id}))
    assert meta["total_count"] == 1

    assert get_success_data(api.get_monitor(monitor["id"], TECH_HEADERS))["monitor_status"] == (
        "APPROVED"
    )

    _, meta = validate_paginated(
        api.list_data_batches(QA_HEADERS, {"monitor_id": monitor["id"]})
    )
    assert meta["total_count"] == 0


def test_a_program_manager_cannot_grant_the_regional_approvals(api):
    """The state programme manager cannot self-grant any federal gate.

    PRD 3.2: "Siting approval belongs to the `EpaRegionalReviewer` and moves a site from `PROPOSED` to `SITING_APPROVED`."
    PRD 3.1: "Federal designations do change, and only an `EpaRegionalReviewer` may change them, by supplying a `new_designation_status` and, optionally, a `determination_note`."
    PRD 3.3: "An `EpaRegionalReviewer` performs it, optionally recording an `approval_note`."

    Design: Corner/rbac/a_program_manager_cannot_grant_the_regional_approvals
    """
    env = operating_site_environment(api)
    monitor = create_monitor(api, env.site_id, env.method_id)
    approve_monitor(api, monitor["id"])
    proposed = create_site(
        api,
        env.network_id,
        site_code="S-002",
        site_type="BACKGROUND",
        latitude=40.1,
        longitude=-105.3,
        population_served=0,
        distance_to_roadway_m=150.0,
    )

    validate_error(
        api.approve_siting(proposed["id"], {"waiver_granted": True}, PM_HEADERS),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.change_designation(env.method_id, {"new_designation_status": "WITHDRAWN"}, PM_HEADERS),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(api.approve_monitor(monitor["id"], {}, PM_HEADERS), ERR_UNAUTHORIZED, 403)

    unchanged_site = get_success_data(api.get_site(proposed["id"], PM_HEADERS))
    assert unchanged_site["status"] == "PROPOSED"
    assert unchanged_site["siting_waiver_granted"] is False

    unchanged_method = get_success_data(api.get_reference_method(env.method_id, PM_HEADERS))
    assert unchanged_method["designation_status"] == "DESIGNATED"
    assert unchanged_method["designation_change_count"] == 0
    assert unchanged_method["withdrawn_on"] is None

    assert get_success_data(api.get_monitor(monitor["id"], TECH_HEADERS))["monitor_status"] == (
        "APPROVED"
    )


def test_every_role_can_read_the_shared_get_endpoints(api):
    """All five roles read the same site row and the same instrument row.

    PRD 2.1: "The five roles are `NetworkAdmin`, `FieldTechnician`, `QaOfficer`, `ProgramManager` and `EpaRegionalReviewer`, spelled exactly so."
    PRD 4: "| GET | `/monitoring-sites/{id}` | Fetch one site with recomputed siting evaluation, operating monitor count and current attainment status. | `NetworkAdmin`, `FieldTechnician`, `QaOfficer`, `ProgramManager`, `EpaRegionalReviewer` |"
    PRD 4: "| GET | `/monitors/{id}` | Fetch one monitor with both recomputed QC postures. | `NetworkAdmin`, `FieldTechnician`, `QaOfficer`, `ProgramManager`, `EpaRegionalReviewer` |"

    Design: Corner/rbac/every_role_can_read_the_shared_get_endpoints
    """
    env = canonical_environment(api)

    reads = [
        validate_success(api.get_site(env.site_id, headers), 200)
        for headers in (ADMIN_HEADERS, TECH_HEADERS, QA_HEADERS, PM_HEADERS, EPA_HEADERS)
    ]
    for row in reads:
        assert row["id"] == env.site_id
        assert row["status"] == "OPERATING"
    assert all(row == reads[0] for row in reads), "the same site must read back identically"

    monitor_reads = [
        validate_success(api.get_monitor(env.monitor_id, headers), 200)
        for headers in (ADMIN_HEADERS, TECH_HEADERS, QA_HEADERS, PM_HEADERS, EPA_HEADERS)
    ]
    for row in monitor_reads:
        assert row["id"] == env.monitor_id
    assert all(row == monitor_reads[0] for row in monitor_reads)


def test_requests_missing_the_auth_headers_are_unauthenticated(api):
    """A missing role, a missing operator and an unknown role all fail at 401.

    PRD 2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role that operator is acting under."
    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the five roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "This check precedes everything else, including request-body parsing and path resolution."

    Design: Corner/rbac/requests_missing_the_auth_headers_are_unauthenticated
    """
    env = operating_site_environment(api)

    validate_error(
        api.get_site(env.site_id, USER_ONLY_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.get_site(env.site_id, ROLE_ONLY_HEADERS), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.approve_siting(env.site_id, {"waiver_granted": True}, BAD_ROLE_HEADERS),
        ERR_UNAUTHENTICATED,
        401,
    )

    assert env.read_site()["status"] == "OPERATING"


def test_the_officer_who_invalidated_hours_cannot_validate_the_quarter(api):
    """The invalidating officer is barred while a second officer may accept.

    The quarter is first opened for review, because the from-state check runs
    ahead of the duty bar, and only then is acceptance attempted twice: once by
    the officer who wrote off the hours and once by an independent officer.

    PRD 2.10: "First, the officer who wrote off hours of a quarter may not be the officer who accepts that quarter for regulatory use."
    PRD 3.5: "The from-state check comes first: a quarter not in `IN_VALIDATION` is rejected with `ERR_INVALID_STATE`, and a quarter already `INVALIDATED` is rejected with `ERR_ALREADY_TERMINAL`."
    PRD 3.5: "Third comes segregation of duties: the calling `X-User-ID` must not appear in the quarter's `invalidation_applied_by_user_ids`, failing which the answer is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_officer_who_invalidated_hours_cannot_validate_the_quarter
    """
    env = canonical_environment(api)
    batch = validate_success(
        api.create_data_batch(data_batch_payload(env.monitor_id, 2025, 1), QA_HEADERS), 201
    )
    validate_success(
        api.create_invalidation(
            batch["id"],
            invalidation_payload(0, 100, "QC_FAILURE", batch["version"]),
            QA_HEADERS,
        ),
        201,
    )
    opened = validate_success(api.begin_validation(batch["id"], {}, QA2_HEADERS), 200)
    assert opened["validation_status"] == "IN_VALIDATION"
    assert opened["invalidation_applied_by_user_ids"] == ["qa-1"]

    validate_error(
        api.validate_batch(batch["id"], {"validation_note": "Quarter reviewed"}, QA_HEADERS),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    barred = get_success_data(api.get_data_batch(batch["id"], QA_HEADERS))
    assert barred["validation_status"] == "IN_VALIDATION"
    assert barred["validated_by_user_id"] is None

    accepted = validate_success(
        api.validate_batch(batch["id"], {"validation_note": "Independent review"}, QA2_HEADERS),
        200,
    )
    assert accepted["validation_status"] == "VALIDATED"
    assert accepted["validated_by_user_id"] == "qa-2"
    assert accepted["invalidation_applied_by_user_ids"] == ["qa-1"]
    assert accepted["invalidated_hour_count"] == 100
    assert accepted["valid_hour_count"] == 2060
    assert_pct(accepted["completeness_pct"], 95.4)
    assert accepted["regulatory_use_eligible"] is True


def test_the_user_who_validated_the_data_cannot_certify_it(api):
    """The duty bar on certification follows the operator across roles.

    One operator identifier validates every quarter while wearing the
    quality-assurance role, and is then refused when the same identifier
    attempts certification under the programme-manager role.

    PRD 2.10: "Second, the manager who validated data may not be the manager who certifies it: certification of an annual package is refused when the calling `X-User-ID` equals the `validated_by_user_id` of any quarter the package selected."
    PRD 3.8: "The segregation gate comes next: the calling `X-User-ID` must not be the `validated_by_user_id` of any quarter the package selected, failing which the answer is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_user_who_validated_the_data_cannot_certify_it
    """
    validator = headers_for("u-1", ROLE_QA_OFFICER)
    certifier_blocked = headers_for("u-1", ROLE_PROGRAM_MANAGER)
    certifier = headers_for("u-2", ROLE_PROGRAM_MANAGER)

    env = canonical_environment(api)
    ingest_worked_example_quarters(env)
    validated = validate_success(
        api.bulk_validate({"monitor_id": env.monitor_id}, validator), 200
    )
    assert len(validated) == 12
    assert all(row["validated_by_user_id"] == "u-1" for row in validated)

    package = validate_success(
        api.create_package(
            package_payload(env.network_id, env.pollutant_id, 2025), certifier
        ),
        201,
    )
    submitted = validate_success(
        api.submit_package(package["id"], {"submission_note": "2025 annual data set"}, certifier),
        200,
    )
    assert submitted["status"] == "SUBMITTED"

    validate_error(
        api.certify_package(
            package["id"],
            {"certification_statement": "I certify the 2025 data set"},
            certifier_blocked,
        ),
        ERR_SEGREGATION_OF_DUTIES,
        403,
    )
    assert get_success_data(api.get_package(package["id"], certifier))["status"] == "SUBMITTED"

    certified = validate_success(
        api.certify_package(
            package["id"], {"certification_statement": "I certify the 2025 data set"}, certifier
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "u-2"

    for quarter in (1, 2, 3, 4):
        row = env.read_batch(2025, quarter)
        assert row["submission_status"] == "CERTIFIED"
        assert row["validation_status"] == "VALIDATED"
    for year in (2023, 2024):
        for quarter in (1, 2, 3, 4):
            row = env.read_batch(year, quarter)
            assert row["submission_status"] == "UNSUBMITTED"
            assert row["validation_status"] == "VALIDATED"
