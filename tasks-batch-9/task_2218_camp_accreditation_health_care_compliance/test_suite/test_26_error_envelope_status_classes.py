"""One walk over the catalogue touches 400, 404, 409, 412 and 422, and every rejection answers with
the same error envelope and leaves no row behind."""

from __future__ import annotations

from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import camp_payload, cycle_payload, visit_payload
from test_helpers.test_users import OFFICER_ONE_HEADERS
from test_helpers.types import (
    CampType,
    HealthStaffingLevel,
    PopulationServed,
    StandardDomain,
    StateLicenseStatus,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

ENVELOPE_STANDARDS = [
    fx.universal_mandatory_standard(
        "SU.1", domain=StandardDomain.SUPERVISION, scoring_weight=1
    )
]


def _assert_error_envelope(response):
    """Every rejection carries meta, response_type error and only the two error fields."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"].startswith("req_")
    assert set(body["data"]) == {"error_id", "message"}
    assert body["data"]["message"].strip()
    return body


def _a_camp_whose_version_the_client_still_remembers(api):
    """The camp version captured at registration goes stale when the licence is recorded."""
    fx.reset_clock(api)
    camp = fx.register_camp(
        api,
        name="Envelope Camp",
        camp_type=CampType.DAY,
        state_code="OH",
        population_served=PopulationServed.YOUTH_ONLY,
        health_staffing_level=HealthStaffingLevel.FIRST_AIDER_ONLY,
    )
    edition, _standards = fx.publish_edition_with_standards(
        api, "ACA-2026-ENV", ENVELOPE_STANDARDS
    )
    licensed = fx.move_state_license(
        api, camp["id"], StateLicenseStatus.ACTIVE, "OH-CAMP-60003"
    )
    assert licensed["version"] == camp["version"] + 1
    return {
        "camp_id": camp["id"],
        "set_id": edition["id"],
        "stale_version": camp["version"],
        "fresh_version": licensed["version"],
    }


def _open_cycle_attempt(api, world, expected_camp_version):
    return api.create_cycle(
        cycle_payload(world["camp_id"], world["set_id"], expected_camp_version, 2026),
        OFFICER_ONE_HEADERS,
    )


def test_a_value_outside_its_declared_enum_is_a_schema_failure(api):
    """PRD §2.5: "the body parses, every required input field is present and non-null, every enum
    value belongs to its declared domain, integers declared non-negative are non-negative,
    calendar dates are ISO 8601 dates and instants are ISO 8601 UTC timestamps:
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/errors/one_envelope_shape_carries_every_status_class_in_the_catalog
    """
    _a_camp_whose_version_the_client_still_remembers(api)

    rejected = api.create_camp(
        camp_payload(
            name="Bad Enum Camp",
            camp_type="GLAMPING",
            state_code="OH",
            population_served=PopulationServed.YOUTH_ONLY,
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(rejected, ApiErrorId.INVALID_REQUEST, 400)
    _assert_error_envelope(rejected)

    # The rejected create left the collection exactly as it was.
    assert validate_paginated(api.list_camps({}, OFFICER_ONE_HEADERS))[1]["total_count"] == 1


def test_a_missing_path_id_and_a_republished_edition_use_the_same_envelope(api):
    """PRD §3.2: "Adding a standard to an edition that is `PUBLISHED` or `RETIRED` is rejected
    with `ERR_STANDARDS_SET_ALREADY_PUBLISHED` (HTTP 409), and so is an attempt to publish an
    edition that is not `DRAFT`."

    Design: Corner/errors/one_envelope_shape_carries_every_status_class_in_the_catalog
    """
    world = _a_camp_whose_version_the_client_still_remembers(api)

    missing = api.get_camp(NON_EXISTENT_UUID, OFFICER_ONE_HEADERS)
    validate_error(missing, ApiErrorId.CAMP_NOT_FOUND, 404)
    _assert_error_envelope(missing)

    republished = api.publish_standards_set(world["set_id"], OFFICER_ONE_HEADERS)
    validate_error(republished, ApiErrorId.STANDARDS_SET_ALREADY_PUBLISHED, 409)
    _assert_error_envelope(republished)


def test_a_version_the_client_legitimately_held_is_refused_as_stale(api):
    """PRD §2.6: "If it does not equal the camp's current `version`, the request is rejected with
    `ERR_STALE_CAMP_VERSION` (HTTP 412)."

    Design: Corner/errors/one_envelope_shape_carries_every_status_class_in_the_catalog
    """
    world = _a_camp_whose_version_the_client_still_remembers(api)

    stale = _open_cycle_attempt(api, world, world["stale_version"])
    validate_error(stale, ApiErrorId.STALE_CAMP_VERSION, 412)
    _assert_error_envelope(stale)
    assert validate_paginated(api.list_cycles({}, OFFICER_ONE_HEADERS))[1]["total_count"] == 0

    # The identical request with the fresh version proves the refusal was about the version.
    opened = validate_success(
        _open_cycle_attempt(api, world, world["fresh_version"]), 201
    )
    assert opened["camp_id"] == world["camp_id"]
    assert opened["cycle_year"] == 2026


def test_an_inverted_window_is_a_temporal_rejection_that_stores_nothing(api):
    """PRD §3.5: "The window must satisfy three conditions together: `window_start_date` on or
    before `window_end_date`, a span of at most fourteen days counting both endpoints, and
    `window_start_date` on or after the logical clock's calendar date. Any violation is
    `ERR_VISIT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/errors/one_envelope_shape_carries_every_status_class_in_the_catalog
    """
    world = _a_camp_whose_version_the_client_still_remembers(api)
    cycle = validate_success(_open_cycle_attempt(api, world, world["fresh_version"]), 201)

    inverted = api.create_visit(
        visit_payload(
            cycle["id"],
            cycle["version"],
            window_start_date="2026-09-01",
            window_end_date="2026-08-31",
        ),
        OFFICER_ONE_HEADERS,
    )
    validate_error(inverted, ApiErrorId.VISIT_WINDOW_INVALID, 422)
    _assert_error_envelope(inverted)

    # Exactly one camp, one edition and one cycle exist, and no visit was ever stored.
    assert validate_paginated(api.list_camps({}, OFFICER_ONE_HEADERS))[1]["total_count"] == 1
    assert (
        validate_paginated(api.list_standards_sets({}, OFFICER_ONE_HEADERS))[1]["total_count"]
        == 1
    )
    assert validate_paginated(api.list_cycles({}, OFFICER_ONE_HEADERS))[1]["total_count"] == 1
    assert validate_paginated(api.list_visits({}, OFFICER_ONE_HEADERS))[1]["total_count"] == 0
