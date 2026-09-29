"""
Entity-surface behaviour: registration defaults, server-sourced system fields,
single-record reads, paginated listings, immutable rows, computed counters and
the not-found and schema-rejection codes that guard each write.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_CITATION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LINE_NOT_FOUND,
    ERR_ZONE_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_immutable_record,
    assert_instant_equals,
    assert_rate_equals,
    assert_versioned_record,
    ids_of,
)
from test_helpers.constants import (
    CLOCK_EPOCH,
    DEFAULT_MAX_CONCURRENT_DEPLOYMENTS,
    DEFAULT_PENALTY_MULTIPLIER_BPS,
    ENFORCEMENT_POLICY_CITATION_IMMEDIATE,
    INSPECTOR_STATUS_ACTIVE,
    MODE_LIGHT_RAIL,
    OUTCOME_WARNING_ISSUED,
    VALIDATION_NO_PROOF,
    ZONE_STATUS_DESIGNATED,
    ZONE_STATUS_DRAFT,
)
from test_helpers.test_users import ANALYST_HEADERS, PLANNER_HEADERS, PLANNER_USER_ID

UNKNOWN_CITATION_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_ZONE_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_LINE_ID = "00000000-0000-4000-8000-0000000000ab"
SECOND_AUDIT_AT = "2026-08-01T02:00:00Z"


def test_a_bare_zone_registration_stamps_every_default_and_system_field(api):
    """
    Registration therefore produces a zone in `DRAFT` and nothing more.  A newly
    registered zone opens with `verified_sign_count` at 0 and
    `signage_compliance_pct` at 0.0, with `designated_at` and `suspension_reason`
    both empty.

    Design: Corner/entities/fare_zone_creation_stamps_defaults_and_system_fields
    """
    fixtures.move_clock(api, CLOCK_EPOCH)

    response = api.create_fare_zone(
        factories.fare_zone_payload(
            zone_code="ZN1", name="Downtown POP Zone", required_sign_count=10
        ),
        PLANNER_HEADERS,
    )
    zone = validate_success(response, expected_status=201)

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"]

    assert zone["designation_status"] == ZONE_STATUS_DRAFT
    assert zone["verified_sign_count"] == 0
    assert_rate_equals(zone["signage_compliance_pct"], 0.0000, "zone.signage_compliance_pct")

    assert zone["penalty_multiplier_bps"] == DEFAULT_PENALTY_MULTIPLIER_BPS
    assert zone["enforcement_policy"] == ENFORCEMENT_POLICY_CITATION_IMMEDIATE
    assert zone["max_concurrent_deployments"] == DEFAULT_MAX_CONCURRENT_DEPLOYMENTS

    assert not zone.get("designated_at")
    assert not zone.get("suspension_reason")

    assert_versioned_record(zone, 1, "zone")
    assert_instant_equals(zone["created_at"], CLOCK_EPOCH, "zone.created_at")


def test_reading_one_zone_returns_the_stored_row_with_a_current_compliance_figure(api):
    """
    The same recomputation happens when a single zone is read, so a zone's
    compliance figure is always current with its audit history.

    Design: Corner/entities/fare_zone_retrieval_returns_the_stored_row
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    created = fixtures.register_zone(api)
    fixtures.file_audit(api, created["id"], 10)

    read = validate_success(api.get_fare_zone(created["id"], ANALYST_HEADERS))

    assert read["id"] == created["id"]
    assert read["zone_code"] == "ZN1"
    assert read["name"] == "Downtown POP Zone"
    assert read["required_sign_count"] == 10
    assert read["verified_sign_count"] == 10
    assert_rate_equals(read["signage_compliance_pct"], 1.0000, "zone.signage_compliance_pct")
    assert read["designation_status"] == ZONE_STATUS_DRAFT


def test_the_zone_listing_pages_with_a_total_count_and_a_has_more_flag(api):
    """
    The `meta` block of a list response carries `limit`, `offset`, `total_count`
    and `has_more`, where `total_count` is the size of the full filtered
    collection before the page window is applied and `has_more` indicates
    whether any records remain beyond the current page.

    Design: Corner/entities/fare_zone_listing_paginates_with_total_count_and_has_more
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    first = fixtures.register_zone(
        api,
        zone_code="ZN1",
        name="Downtown POP Zone",
        required_sign_count=10,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    second = fixtures.register_zone(
        api,
        zone_code="ZN2",
        name="Midtown POP Zone",
        required_sign_count=6,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    third = fixtures.register_zone(
        api,
        zone_code="ZN3",
        name="Airport POP Zone",
        required_sign_count=4,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )

    page_one_response = api.list_fare_zones(ANALYST_HEADERS, {"limit": 2, "offset": 0})
    page_one, meta_one = validate_paginated(page_one_response)
    assert page_one_response.json()["response_type"] == "array"
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    page_two, meta_two = validate_paginated(
        api.list_fare_zones(ANALYST_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["offset"] == 2

    seen = ids_of(page_one) + ids_of(page_two)
    assert len(seen) == len(set(seen))
    assert set(seen) == {first["id"], second["id"], third["id"]}

    designated, meta_designated = validate_paginated(
        api.list_fare_zones(ANALYST_HEADERS, {"designation_status": ZONE_STATUS_DESIGNATED})
    )
    assert designated == []
    assert meta_designated["total_count"] == 0


def test_an_unknown_citation_id_returns_the_citation_specific_not_found_code(api):
    """
    Identifiers embedded in a URL path are resolved strictly left to right, and
    the first one that fails to resolve determines the error returned.  Each
    resource kind has its own not-found code, all at HTTP 404.

    Design: Corner/entities/citation_read_with_unknown_id_returns_not_found
    """
    fixtures.move_clock(api, CLOCK_EPOCH)

    response = api.get_citation(UNKNOWN_CITATION_ID, PLANNER_HEADERS)
    validate_error(response, ERR_CITATION_NOT_FOUND, 404)

    envelope = response.json()
    assert envelope["response_type"] == "error"
    assert envelope["data"]["message"]


def test_a_transit_line_without_a_mode_is_a_schema_rejection_and_persists_nothing(api):
    """
    Then request-body schema — required fields present, correct JSON types, enum
    members drawn from their declared sets, and numeric fields within their
    declared ranges (`ERR_INVALID_REQUEST`, HTTP 400, on every POST endpoint).

    Design: Corner/entities/transit_line_creation_without_mode_returns_invalid_request
    """
    fixtures.move_clock(api, CLOCK_EPOCH)

    validate_error(
        api.create_transit_line(
            {"line_code": "L1", "daily_boardings": 42000, "baseline_evasion_rate_bps": 600},
            PLANNER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    validate_error(
        api.get_transit_line(UNKNOWN_LINE_ID, PLANNER_HEADERS), ERR_LINE_NOT_FOUND, 404
    )


def test_an_enforcement_policy_outside_the_declared_set_is_refused(api):
    """
    `enforcement_policy`, the citation-versus-warning stance in force inside the
    zone, defaults to `CITATION_IMMEDIATE` and must be either `WARNING_FIRST` or
    `CITATION_IMMEDIATE`.

    Design: Corner/entities/fare_zone_creation_with_unknown_enforcement_policy_returns_invalid_request
    """
    fixtures.move_clock(api, CLOCK_EPOCH)

    validate_error(
        api.create_fare_zone(
            {
                "zone_code": "ZN9",
                "name": "Bad Enum Zone",
                "required_sign_count": 10,
                "enforcement_policy": "ZERO_TOLERANCE",
            },
            PLANNER_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    _, meta = validate_paginated(api.list_fare_zones(ANALYST_HEADERS))
    assert meta["total_count"] == 0


def test_an_inspector_registered_without_a_status_opens_active_with_no_citations(api):
    """
    The optional `status` defaults to `ACTIVE` and must be either `ACTIVE` or
    `SUSPENDED`.  A newly registered inspector's `citations_issued_count` opens
    at 0.

    Design: Corner/entities/inspector_status_defaults_to_active_when_omitted
    """
    fixtures.move_clock(api, CLOCK_EPOCH)

    inspector = validate_success(
        api.create_inspector(
            factories.inspector_payload(
                badge_number="B-100",
                display_name="Inspector One",
                certification_expiry="2027-01-01T00:00:00Z",
            ),
            PLANNER_HEADERS,
        ),
        expected_status=201,
    )

    assert inspector["status"] == INSPECTOR_STATUS_ACTIVE
    assert inspector["citations_issued_count"] == 0
    assert_instant_equals(
        inspector["certification_expiry"],
        "2027-01-01T00:00:00Z",
        "inspector.certification_expiry",
    )
    assert_versioned_record(inspector, 1, "inspector")


def test_a_transit_lines_identity_fields_come_from_the_server_and_the_clock(api):
    """
    Every persisted record is addressed by an `id` that the server mints as a
    UUID.  Most records additionally carry `updated_at` ... and `version`, an
    integer that starts at 1 and is incremented by exactly 1 on every mutation
    of that record.

    Design: Corner/entities/transit_line_system_fields_are_server_generated_and_input_ignored
    """
    fixtures.move_clock(api, CLOCK_EPOCH)

    payload = factories.transit_line_payload(
        line_code="L1", mode=MODE_LIGHT_RAIL, daily_boardings=42000, baseline_evasion_rate_bps=600
    )
    line = validate_success(api.create_transit_line(payload, PLANNER_HEADERS), expected_status=201)

    assert_versioned_record(line, 1, "line")
    assert_instant_equals(line["created_at"], CLOCK_EPOCH, "line.created_at")
    assert_instant_equals(line["updated_at"], CLOCK_EPOCH, "line.updated_at")
    assert line["id"] not in payload.values()

    read_back = validate_success(api.get_transit_line(line["id"], PLANNER_HEADERS))
    assert read_back["id"] == line["id"]
    assert read_back["version"] == 1


def test_a_corrected_sign_count_is_a_second_append_only_audit_row(api):
    """
    `SignageAudit` is an append-only physical count.  None of the three is ever
    rewritten; corrections are made by appending a new row, and in the ledger's
    case by appending a reversal.

    Design: Corner/entities/signage_audit_is_immutable_and_carries_no_version_field
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    zone = fixtures.register_zone(
        api,
        penalty_multiplier_bps=None,
        enforcement_policy=None,
        max_concurrent_deployments=None,
    )
    first = fixtures.file_audit(
        api, zone["id"], 8, deficiency_note="Two shelter signs missing."
    )

    second = fixtures.file_audit(
        api,
        zone["id"],
        10,
        audited_at=SECOND_AUDIT_AT,
        deficiency_note="Signs restored.",
    )

    rows, meta = validate_paginated(api.list_zone_signage_audits(zone["id"], ANALYST_HEADERS))
    assert meta["total_count"] == 2
    assert ids_of(rows) == [first["id"], second["id"]]
    assert [row["signs_verified_count"] for row in rows] == [8, 10]

    for row in rows:
        assert_immutable_record(row, "signage audit")

    assert second["auditor_user_id"] == PLANNER_USER_ID

    refreshed = fixtures.read_zone(api, zone["id"])
    assert refreshed["verified_sign_count"] == 10
    assert_rate_equals(
        refreshed["signage_compliance_pct"], 1.0000, "zone.signage_compliance_pct"
    )


def test_a_junction_row_resolves_its_zone_parent_before_its_line_parent(api):
    """
    Creating a zone-line assignment resolves `zone_id` before `line_id`.
    Body-borne reference failures reuse the same 404 codes as path failures.

    Design: Corner/entities/zone_line_assignment_with_unknown_zone_returns_zone_not_found
    """
    fixtures.move_clock(api, CLOCK_EPOCH)
    line = fixtures.register_line(api)

    validate_error(
        api.create_zone_line_assignment(
            factories.zone_line_assignment_payload(
                zone_id=UNKNOWN_ZONE_ID,
                line_id=line["id"],
                platform_segment_count=4,
                effective_from=CLOCK_EPOCH,
            ),
            PLANNER_HEADERS,
        ),
        ERR_ZONE_NOT_FOUND,
        404,
    )

    rows, meta = validate_paginated(
        api.list_zone_line_assignments(ANALYST_HEADERS, {"line_id": line["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_rider_counters_open_at_zero_and_move_only_on_a_resolved_encounter(api):
    """
    Two counters open at 0 and are maintained thereafter: `prior_warning_count`
    is the number of encounters for this rider whose `outcome` is
    `WARNING_ISSUED`, and `prior_citation_count` is the number of citations for
    this rider whose `adjudication_status` is one of `ISSUED`, `CONTESTED`,
    `UPHELD` or `REDUCED`.

    Design: Corner/entities/rider_counter_fields_are_computed_from_encounter_history
    """
    env = fixtures.build_environment(api)
    rider = env["rider"]
    assert rider["prior_warning_count"] == 0
    assert rider["prior_citation_count"] == 0

    deployment = fixtures.build_active_deployment(api, env)
    encounter = fixtures.build_pending_encounter(api, env, deployment)

    resolved = fixtures.resolve(
        api, encounter["id"], env["inspector"]["id"], OUTCOME_WARNING_ISSUED
    )

    assert resolved["validation_result"] == VALIDATION_NO_PROOF
    assert resolved["outcome"] == OUTCOME_WARNING_ISSUED

    after = fixtures.read_rider(api, rider["id"])
    assert after["prior_warning_count"] == 1
    assert after["prior_citation_count"] == 0

    closed_view = fixtures.read_deployment(api, deployment["id"])
    assert closed_view["achieved_sample_count"] == 1
    assert_rate_equals(
        closed_view["sample_adequacy_ratio"], 0.2000, "deployment.sample_adequacy_ratio"
    )
