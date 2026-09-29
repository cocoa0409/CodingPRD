"""Field contracts of the program's rows as they are written and read back.

This file covers what a row looks like the moment the server creates it and when
a client reads it again: the server-minted identifier and audit stamps, the
values that fall back to declared defaults, the figures the server computes from
the payload rather than accepting from it, the two append-only rows that carry no
version at all, the refusals that guard required inputs and enum vocabularies,
the resolution of parent and body foreign keys ahead of business rules, and the
envelopes the collection reads wrap their rows in.
"""

import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import assertions as a
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

# Identifiers that name no row in a freshly launched database.
UNKNOWN_OFFERING_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_AGENCY_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_POAM_ITEM_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_AUTHORIZATION_ID = "44444444-4444-4444-8444-444444444444"


# ---------------------------------------------------------------------------
# Agency registration
# ---------------------------------------------------------------------------


def test_agency_registration_returns_the_whole_row_with_its_counters_at_zero(client):
    """Registering an agency echoes the submitted registry fields and opens all three system counters at zero.

    PRD: "All three counters start at 0."

    Design: Corner/entities/agency_creation_returns_the_whole_row_inside_the_success_envelope
    """
    response = client.create_agency(
        f.build_agency_payload(
            name="Department of Transportation",
            agency_code="DOT",
            status="ACTIVE",
            sponsorship_capacity=2,
        ),
        users.BOARD_HEADERS,
    )
    agency = validate_success(response, 201)

    envelope = response.json()
    assert envelope["response_type"] == "object", (
        f"a single row must be wrapped as an object, got {envelope['response_type']}"
    )
    assert envelope["meta"]["api_request_id"], "meta.api_request_id must be present"
    a.parse_instant(envelope["meta"]["api_request_timestamp"])

    assert agency["name"] == "Department of Transportation"
    assert agency["agency_code"] == "DOT"
    assert agency["status"] == "ACTIVE"
    a.assert_integer(agency["sponsorship_capacity"], 2, "sponsorship_capacity")
    a.assert_integer(agency["sponsored_offering_count"], 0, "sponsored_offering_count")
    a.assert_integer(agency["reuse_grant_count"], 0, "reuse_grant_count")
    a.assert_integer(agency["open_notice_count"], 0, "open_notice_count")

    assert is_valid_uuid(agency["id"]), f"id must be a bare UUID, got {agency['id']!r}"
    a.assert_audit_triplet(agency, "agency")
    a.assert_integer(agency["version"], 1, "agency.version")
    a.assert_instant(agency["created_at"], k.CLOCK_STARTUP_DEFAULT, "created_at")
    a.assert_instant(agency["updated_at"], k.CLOCK_STARTUP_DEFAULT, "updated_at")


def test_agency_read_back_matches_the_registration_response_and_leaves_it_unversioned(
    client,
):
    """Reading an agency returns exactly the row registration returned, and the read is not a mutation.

    PRD: "`version` (integer): starts at 1 and increments by one on every mutation of the row."

    Design: Corner/entities/agency_creation_returns_the_whole_row_inside_the_success_envelope
    """
    created = fx.create_agency(
        client, name="Department of Transportation", agency_code="DOT", sponsorship_capacity=2
    )

    read_back = validate_success(
        client.get_agency(created["id"], users.CSP_LEAD_HEADERS), 200
    )

    assert read_back == created, (
        f"the stored row differs from the created row: {read_back} vs {created}"
    )
    a.assert_integer(read_back["version"], 1, "agency.version after a read")
    a.assert_instant(read_back["updated_at"], created["updated_at"], "updated_at")


# ---------------------------------------------------------------------------
# Offering reads
# ---------------------------------------------------------------------------


def test_fresh_offering_read_carries_its_pre_categorization_fields_as_null(client):
    """A newly registered offering reads back with every downstream field still null and every counter at zero.

    PRD: "A fresh offering has `authorization_path`, `sponsor_agency_id`, `baseline_id`, `preliminary_impact_level` and `final_impact_level` all null, `boundary_version` at 1, and `included_service_count`, `open_package_count` and `superseded_package_count` all at 0."

    Design: Corner/entities/offering_read_returns_the_stored_row_with_its_null_valued_optional_fields
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    response = client.get_offering(env["offering_id"], users.ASSESSOR_HEADERS)
    offering = validate_success(response, 200)
    assert response.json()["response_type"] == "object"

    assert offering["name"] == "GovCloud Compute"
    assert offering["provider_name"] == "Aurora Cloud"
    assert offering["service_model"] == "IAAS"
    assert offering["deployment_model"] == "GOV_COMMUNITY"
    a.assert_money(offering["assessment_budget_usd"], 400000.00, "assessment_budget_usd")
    assert offering["external_dependency_impact_level"] == "LOW"
    assert offering["owner_user_id"] == users.CSP_LEAD_1
    assert offering["status"] == "DRAFT"

    for field in (
        "authorization_path",
        "sponsor_agency_id",
        "baseline_id",
        "preliminary_impact_level",
        "final_impact_level",
    ):
        assert offering[field] is None, f"{field} must be null on a fresh offering"

    a.assert_integer(offering["boundary_version"], 1, "boundary_version")
    a.assert_integer(offering["included_service_count"], 0, "included_service_count")
    a.assert_integer(offering["open_package_count"], 0, "open_package_count")
    a.assert_integer(offering["superseded_package_count"], 0, "superseded_package_count")
    a.assert_integer(offering["version"], 1, "offering.version")
    a.assert_instant(offering["created_at"], fx.SETUP_CLOCK, "created_at")


def test_offering_read_is_open_to_every_role_not_only_its_owning_lead(client):
    """The offering read serves the same stored row to all four roles, owner or not.

    PRD: "All read endpoints in §4 are open to all four roles, with the single exception described at the end of this subsection."

    Design: Corner/entities/offering_read_returns_the_stored_row_with_its_null_valued_optional_fields
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    for headers in (
        env["lead_headers"],
        users.CSP_LEAD_2_HEADERS,
        users.ASSESSOR_HEADERS,
        users.BOARD_HEADERS,
        env["agency_headers"],
    ):
        offering = validate_success(
            client.get_offering(env["offering_id"], headers), 200
        )
        assert offering["id"] == env["offering_id"]
        assert offering["owner_user_id"] == users.CSP_LEAD_1
        assert offering["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Offering listing
# ---------------------------------------------------------------------------


def _three_draft_offerings(client):
    """Register three DRAFT offerings against one reference registry."""
    env = fx.seed_reference_data(client)
    env = fx.seed_draft_offering(client, env, name="GovCloud Compute")
    env = fx.seed_draft_offering(client, env, name="GovCloud Storage", key="offering_b")
    env = fx.seed_draft_offering(client, env, name="GovCloud Analytics", key="offering_c")
    return env


def test_offering_list_reports_the_unwindowed_total_while_paging_two_at_a_time(client):
    """Paging the offering list two rows at a time reports the full match count and hands back disjoint pages.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied."

    Design: Corner/entities/offering_list_pages_with_total_count_and_has_more
    """
    env = _three_draft_offerings(client)

    first_page, first_meta = validate_paginated(
        client.list_offerings(env["lead_headers"], {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"expected 2 rows on the first page, got {len(first_page)}"
    a.assert_integer(first_meta["limit"], 2, "meta.limit")
    a.assert_integer(first_meta["offset"], 0, "meta.offset")
    a.assert_integer(first_meta["total_count"], 3, "meta.total_count")
    assert first_meta["has_more"] is True, "a third row remains, so has_more must be true"

    second_page, second_meta = validate_paginated(
        client.list_offerings(env["lead_headers"], {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"expected 1 row on the second page, got {len(second_page)}"
    a.assert_integer(second_meta["offset"], 2, "meta.offset")
    a.assert_integer(second_meta["total_count"], 3, "meta.total_count")
    assert second_meta["has_more"] is False, "the second page exhausts the match set"

    assert not set(a.ids_of(first_page)) & set(a.ids_of(second_page)), (
        "the two pages must not share a row"
    )


def test_offering_list_without_a_limit_falls_back_to_ten_rows_from_the_start(client):
    """An offering list call that names no window takes the default page of ten rows from offset zero.

    PRD: "`limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."

    Design: Corner/entities/offering_list_pages_with_total_count_and_has_more
    """
    env = _three_draft_offerings(client)

    rows, meta = validate_paginated(
        client.list_offerings(env["lead_headers"], {"status": "DRAFT"})
    )

    a.assert_integer(meta["limit"], k.LIMIT_DEFAULT, "meta.limit")
    a.assert_integer(meta["offset"], k.OFFSET_DEFAULT, "meta.offset")
    a.assert_integer(meta["total_count"], 3, "meta.total_count")
    assert len(rows) == 3, f"all three drafts fit the default page, got {len(rows)}"
    assert meta["has_more"] is False, "one page holds every match"


def test_offering_status_filter_that_matches_nothing_returns_an_empty_page(client):
    """Filtering the offering list on a status no row holds narrows the page to nothing rather than failing.

    PRD: "The non-foreign-key filters of that same read — `status` and `authorization_path` — behave normally and simply narrow the result set."

    Design: Corner/entities/offering_list_pages_with_total_count_and_has_more
    """
    env = _three_draft_offerings(client)

    response = client.list_offerings(env["lead_headers"], {"status": "AUTHORIZED"})
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert rows == [], f"no offering is AUTHORIZED, got {rows}"
    a.assert_integer(meta["total_count"], 0, "meta.total_count")
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Unknown identifiers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "collection, unknown_id, expected_error",
    [
        ("offering", UNKNOWN_OFFERING_ID, errors.ERR_OFFERING_NOT_FOUND),
        ("agency", UNKNOWN_AGENCY_ID, errors.ERR_AGENCY_NOT_FOUND),
        ("poam_item", UNKNOWN_POAM_ITEM_ID, errors.ERR_POAM_ITEM_NOT_FOUND),
    ],
)
def test_read_of_an_unknown_identifier_raises_the_error_of_that_collection(
    client, collection, unknown_id, expected_error
):
    """Each single-row read answers an identifier that names no row with the 404 belonging to its own type.

    PRD: "Every identifier in the request path exists, resolved left to right — the corresponding 404."

    Design: Corner/entities/reads_of_unknown_ids_return_the_entity_specific_404
    """
    reads = {
        "offering": lambda: client.get_offering(unknown_id, users.CSP_LEAD_HEADERS),
        "agency": lambda: client.get_agency(unknown_id, users.CSP_LEAD_HEADERS),
        "poam_item": lambda: client.get_poam_item(unknown_id, users.CSP_LEAD_HEADERS),
    }

    response = reads[collection]()
    body = validate_error(response, expected_error, 404)

    assert body["message"], "an error body must carry a non-empty message"
    assert "id" not in body, "a failed read must not hand back a row identifier"

    _, meta = validate_paginated(client.list_offerings(users.BOARD_HEADERS))
    a.assert_integer(meta["total_count"], 0, "offerings after a failed read")


# ---------------------------------------------------------------------------
# Required inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    [
        "name",
        "provider_name",
        "service_model",
        "deployment_model",
        "assessment_budget_usd",
    ],
)
def test_offering_registration_missing_one_required_input_is_refused(
    client, missing_field
):
    """Dropping any one of the offering's required inputs is a malformed request and writes no row.

    PRD: "Request shape: required fields present, enum members legal, numbers positive where the field demands it, arrays non-empty and duplicate-free (with the single exception of the assessment report's `findings` array, which may legally be empty), `period_month` well formed, pagination inside its bounds — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/offering_creation_without_a_required_input_is_a_400
    """
    payload = f.build_offering_payload(**{missing_field: f.OMIT})
    assert missing_field not in payload

    response = client.create_offering(payload, users.CSP_LEAD_HEADERS)
    validate_error(response, errors.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(client.list_offerings(users.CSP_LEAD_HEADERS))
    a.assert_integer(meta["total_count"], 0, "offerings after a refused registration")


def test_agency_registration_without_a_name_is_refused(client):
    """An agency registration that omits the display name is refused as malformed.

    PRD: "Request shape: required fields present, enum members legal, numbers positive where the field demands it, arrays non-empty and duplicate-free (with the single exception of the assessment report's `findings` array, which may legally be empty), `period_month` well formed, pagination inside its bounds — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/offering_creation_without_a_required_input_is_a_400
    """
    payload = f.build_agency_payload(name=f.OMIT, agency_code="DOT")
    assert "name" not in payload

    response = client.create_agency(payload, users.BOARD_HEADERS)
    validate_error(response, errors.ERR_INVALID_REQUEST, 400)


# ---------------------------------------------------------------------------
# Declared defaults
# ---------------------------------------------------------------------------


def test_agency_registered_without_a_status_or_capacity_takes_the_registry_defaults(
    client,
):
    """An agency registered with nothing but its name and code opens ACTIVE with the rationed default capacity.

    PRD: "An agency's `status` is either `ACTIVE` or `INACTIVE` and defaults to `ACTIVE`; only an `ACTIVE` agency may take on a new sponsorship."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_the_declared_defaults
    """
    payload = f.build_agency_payload(
        name="Environmental Protection Agency",
        agency_code="EPA",
        sponsorship_capacity=f.OMIT,
    )
    assert "sponsorship_capacity" not in payload and "status" not in payload

    agency = validate_success(client.create_agency(payload, users.BOARD_HEADERS), 201)

    assert agency["status"] == "ACTIVE"
    a.assert_integer(
        agency["sponsorship_capacity"],
        k.SPONSORSHIP_CAPACITY_DEFAULT,
        "sponsorship_capacity",
    )
    a.assert_integer(agency["sponsored_offering_count"], 0, "sponsored_offering_count")
    a.assert_integer(agency["reuse_grant_count"], 0, "reuse_grant_count")
    a.assert_integer(agency["open_notice_count"], 0, "open_notice_count")


def test_control_implementation_recorded_bare_is_planned_and_undocumented(client):
    """A control implementation recorded with nothing but its control and family opens as planned work with no matrix prose.

    PRD: "Its `implementation_status` is one of `IMPLEMENTED`, `PARTIALLY_IMPLEMENTED`, `PLANNED`, `ALTERNATIVE_IMPLEMENTATION` or `NOT_APPLICABLE`, defaulting to `PLANNED`."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_the_declared_defaults
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))

    payload = f.build_control_implementation_payload(
        env["offering_id"],
        control_id="AC-2",
        family_code="AC",
        implementation_status=f.OMIT,
        crm_documented=False,
    )
    del payload["crm_documented"]
    assert set(payload) == {"offering_id", "control_id", "family_code"}

    row = validate_success(
        client.create_control_implementation(payload, env["lead_headers"]), 201
    )

    assert row["implementation_status"] == "PLANNED"
    assert row["crm_documented"] is False
    assert row["customer_responsibility_text"] is None
    assert row["inherited_from_offering_id"] is None
    a.assert_integer(row["version"], 1, "control implementation version")


def test_offering_registered_without_an_external_dependency_level_leans_on_low(client):
    """An offering that declares no external dependency level is treated as leaning on LOW systems only.

    PRD: "Optionally the lead declares `external_dependency_impact_level`, the highest impact level of the external systems the offering leans on; it defaults to `LOW`."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_the_declared_defaults
    """
    payload = f.build_offering_payload()
    assert "external_dependency_impact_level" not in payload

    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))
    offering = fx.read_offering(client, env["offering_id"])

    assert offering["external_dependency_impact_level"] == "LOW"
    assert offering["final_impact_level"] == "MODERATE"


def test_coverage_of_an_offering_whose_only_control_is_planned_is_zero(client):
    """Planned work earns no coverage, so the computed read divides zero documented controls by the full requirement weight.

    PRD: "For each remaining family, count the offering's control implementations whose `family_code` matches that family, whose `implementation_status` is either `IMPLEMENTED` or `PARTIALLY_IMPLEMENTED`, and whose `crm_documented` is true — implementations that are `PLANNED`, `ALTERNATIVE_IMPLEMENTATION` or `NOT_APPLICABLE` never count, and neither does an implementation whose matrix entry is undocumented."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_the_declared_defaults
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))
    payload = f.build_control_implementation_payload(
        env["offering_id"],
        control_id="AC-2",
        family_code="AC",
        implementation_status=f.OMIT,
        crm_documented=False,
    )
    del payload["crm_documented"]
    validate_success(
        client.create_control_implementation(payload, env["lead_headers"]), 201
    )

    coverage = validate_success(
        client.get_crm_coverage(env["offering_id"], env["lead_headers"]), 200
    )

    a.assert_money(coverage["overall_coverage_pct"], 0.00, "overall_coverage_pct")
    a.assert_integer(coverage["weight_total"], 3, "weight_total")

    breakdown = coverage["family_breakdown"]
    assert len(breakdown) == 2, f"the baseline has two families, got {len(breakdown)}"
    assert [row["family_code"] for row in breakdown] == ["AC", "SC"], (
        f"families must walk in priority order, got {[r['family_code'] for r in breakdown]}"
    )


# ---------------------------------------------------------------------------
# Control baselines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "impact_level, families, expected_total",
    [
        ("MODERATE", [("AC", 2, 1), ("SC", 1, 2)], 3),
        ("HIGH", [("AC", 4, 1), ("SC", 2, 2)], 6),
        ("LOW", [("AC", 1, 1), ("CM", 0, 2)], 1),
    ],
)
def test_baseline_requirement_total_is_summed_across_its_families(
    client, impact_level, families, expected_total
):
    """Publishing a baseline totals the per-family requirement counts into one figure for the whole baseline.

    PRD: "On publication the server computes `total_required_controls` as the sum of the `required_control_count` values across all families."

    Design: Corner/entities/control_baseline_total_required_controls_is_summed_from_the_families_array
    """
    submitted = [f.build_family(code, count, rank) for code, count, rank in families]

    response = client.create_control_baseline(
        f.build_baseline_payload(
            impact_level=impact_level, families=submitted, retired=f.OMIT
        ),
        users.BOARD_HEADERS,
    )
    baseline = validate_success(response, 201)

    assert response.json()["response_type"] == "object"
    assert baseline["impact_level"] == impact_level
    a.assert_integer(
        baseline["total_required_controls"], expected_total, "total_required_controls"
    )
    assert len(baseline["families"]) == 2, (
        f"both submitted families must be kept, got {baseline['families']}"
    )
    assert [row["family_code"] for row in baseline["families"]] == [
        row["family_code"] for row in submitted
    ], "the families array keeps the submitted order"


def test_baseline_published_without_a_retirement_flag_is_selectable(client):
    """A baseline published without saying otherwise is not retired, so it stays selectable for its impact level.

    PRD: "Publishing one records the `impact_level` it applies to — `LOW`, `MODERATE` or `HIGH` — a human-readable `version_label` such as REV5-MOD, an `effective_from` instant from which it becomes the selectable baseline for its impact level, and a `retired` flag defaulting to false that excludes it from selection when set."

    Design: Corner/entities/control_baseline_total_required_controls_is_summed_from_the_families_array
    """
    payload = f.build_baseline_payload(retired=f.OMIT)
    assert "retired" not in payload

    baseline = validate_success(
        client.create_control_baseline(payload, users.BOARD_HEADERS), 201
    )

    assert baseline["retired"] is False
    assert baseline["impact_level"] == "MODERATE"
    assert baseline["version_label"] == "Rev5-MODERATE"
    a.assert_instant(baseline["effective_from"], "2026-01-01T00:00:00Z", "effective_from")


# ---------------------------------------------------------------------------
# Server-minted system fields
# ---------------------------------------------------------------------------


def test_offering_ownership_and_stamps_come_from_the_caller_and_the_clock(client):
    """Two leads registering offerings at two clock settings each own their own row, stamped at the instant they acted.

    PRD: "The server stamps `owner_user_id` from the acting `X-User-ID` and places the offering in status `DRAFT`."

    Design: Corner/entities/offering_system_fields_are_minted_by_the_server_from_the_headers_and_the_clock
    """
    fx.set_clock(client, "2026-02-01T00:00:00Z")
    first = validate_success(
        client.create_offering(
            f.build_offering_payload(name="GovCloud Compute"), users.CSP_LEAD_HEADERS
        ),
        201,
    )

    fx.set_clock(client, "2026-04-15T09:30:00Z")
    second = validate_success(
        client.create_offering(
            f.build_offering_payload(
                name="GovCloud Storage",
                assessment_budget_usd=250000.00,
                service_model="PAAS",
                deployment_model="HYBRID",
            ),
            users.CSP_LEAD_2_HEADERS,
        ),
        201,
    )

    assert first["owner_user_id"] == users.CSP_LEAD_1
    a.assert_instant(first["created_at"], "2026-02-01T00:00:00Z", "first created_at")
    a.assert_instant(first["updated_at"], "2026-02-01T00:00:00Z", "first updated_at")

    assert second["owner_user_id"] == users.CSP_LEAD_2
    a.assert_instant(second["created_at"], "2026-04-15T09:30:00Z", "second created_at")
    a.assert_instant(second["updated_at"], "2026-04-15T09:30:00Z", "second updated_at")

    assert first["id"] != second["id"], "each offering gets its own identifier"
    for offering in (first, second):
        assert is_valid_uuid(offering["id"])
        assert offering["status"] == "DRAFT"
        a.assert_integer(offering["boundary_version"], 1, "boundary_version")
        a.assert_integer(offering["included_service_count"], 0, "included_service_count")
        a.assert_integer(offering["open_package_count"], 0, "open_package_count")
        a.assert_integer(
            offering["superseded_package_count"], 0, "superseded_package_count"
        )
        a.assert_integer(offering["version"], 1, "offering.version")


def test_clock_move_reports_the_new_setting_that_later_rows_are_stamped_with(client):
    """Moving the logical clock reports the instant it now reads, and rows written afterwards carry that instant.

    PRD: "A `ProgramBoardReviewer` may move the clock by supplying a `to_iso8601` instant; the response reports the new setting as `current_utc`."

    Design: Corner/entities/offering_system_fields_are_minted_by_the_server_from_the_headers_and_the_clock
    """
    response = client.set_clock(
        f.build_clock_payload("2026-04-15T09:30:00Z"), users.BOARD_HEADERS
    )
    clock = validate_success(response, 200)

    a.assert_instant(clock["current_utc"], "2026-04-15T09:30:00Z", "current_utc")

    offering = validate_success(
        client.create_offering(
            f.build_offering_payload(name="GovCloud Storage"), users.CSP_LEAD_2_HEADERS
        ),
        201,
    )
    a.assert_instant(offering["created_at"], clock["current_utc"], "created_at")


# ---------------------------------------------------------------------------
# Enum and range constraints
# ---------------------------------------------------------------------------


def test_data_category_rating_outside_the_fips_vocabulary_is_refused(client):
    """A data category rated outside the three FIPS levels is refused, while the same call with a legal rating is stored.

    PRD: "Request shape: required fields present, enum members legal, numbers positive where the field demands it, arrays non-empty and duplicate-free (with the single exception of the assessment report's `findings` array, which may legally be empty), `period_month` well formed, pagination inside its bounds — `ERR_INVALID_REQUEST`."

    Design: Corner/entities/enum_membership_and_numeric_range_constraints_are_enforced_on_write
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    refused = client.create_data_category(
        env["offering_id"],
        f.build_data_category_payload(confidentiality_impact="CRITICAL"),
        env["lead_headers"],
    )
    validate_error(refused, errors.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        client.list_data_categories(env["offering_id"], users.BOARD_HEADERS)
    )
    a.assert_integer(meta["total_count"], 0, "categories after a refused declaration")

    accepted = validate_success(
        client.create_data_category(
            env["offering_id"],
            f.build_data_category_payload(confidentiality_impact="MODERATE"),
            env["lead_headers"],
        ),
        201,
    )
    assert accepted["confidentiality_impact"] == "MODERATE"
    assert accepted["status"] == "DECLARED"

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "MODERATE"


@pytest.mark.parametrize(
    "overrides",
    [
        {"assessment_budget_usd": 0.0},
        {"service_model": "SERVERLESS"},
    ],
)
def test_offering_registration_outside_its_declared_vocabularies_is_refused(
    client, overrides
):
    """A registration whose budget is not above zero, or whose service model is not one of the three, is refused.

    PRD: "A `CspComplianceLead` opens the process by registering a **cloud service offering**, supplying its `name`, the `provider_name` of the operating organization, a `service_model` of `IAAS`, `PAAS` or `SAAS`, a `deployment_model` of `GOV_COMMUNITY`, `PUBLIC`, `HYBRID` or `PRIVATE`, and an `assessment_budget_usd` — the finance-approved spend authorization for third-party assessment, which must be greater than zero and is held to two decimal places."

    Design: Corner/entities/enum_membership_and_numeric_range_constraints_are_enforced_on_write
    """
    response = client.create_offering(
        f.build_offering_payload(name="GovCloud Compute", **overrides),
        users.CSP_LEAD_HEADERS,
    )
    validate_error(response, errors.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(client.list_offerings(users.CSP_LEAD_HEADERS))
    a.assert_integer(meta["total_count"], 0, "offerings after a refused registration")


# ---------------------------------------------------------------------------
# The append-only rows
# ---------------------------------------------------------------------------


def test_published_baseline_carries_an_identity_stamp_and_no_version(client):
    """A published baseline is never edited, so its row carries a creation stamp but no update stamp and no version.

    PRD: "Two resource types are exceptions and carry only `id` and `created_at`: a `ControlBaseline`, which is published once and never edited, and a `ScanSubmission`, which is an immutable append-only record of one monthly scan delivery."

    Design: Corner/entities/the_two_append_only_entities_expose_no_version_and_no_update_endpoint
    """
    fx.set_clock(client, fx.SETUP_CLOCK)

    baseline = validate_success(
        client.create_control_baseline(
            f.build_baseline_payload(
                impact_level="HIGH",
                families=[f.build_family("AC", 4, 1)],
                effective_from="2026-01-15T00:00:00Z",
                retired=f.OMIT,
            ),
            users.BOARD_HEADERS,
        ),
        201,
    )

    a.assert_identity_only(baseline, "control baseline")
    assert is_valid_uuid(baseline["id"])
    a.assert_instant(baseline["created_at"], fx.SETUP_CLOCK, "created_at")
    for field in (
        "impact_level",
        "version_label",
        "effective_from",
        "retired",
        "families",
        "total_required_controls",
    ):
        assert field in baseline, f"a baseline row must carry {field}"
    a.assert_integer(baseline["total_required_controls"], 4, "total_required_controls")


def test_scan_submission_carries_an_identity_stamp_and_no_version(client):
    """A monthly scan delivery is an append-only record, so its row exposes neither an update stamp nor a version.

    PRD: "Neither of these two carries `updated_at` and neither carries `version` — those fields are absent from their responses entirely."

    Design: Corner/entities/the_two_append_only_entities_expose_no_version_and_no_update_endpoint
    """
    env = fx.seed_authorized_offering(client)

    submission = validate_success(
        client.create_scan_submission(
            env["period_id"], f.build_scan_submission_payload(), env["lead_headers"]
        ),
        201,
    )

    a.assert_identity_only(submission, "scan submission")
    assert is_valid_uuid(submission["id"])
    a.assert_instant(submission["created_at"], fx.AUTHORIZATION_CLOCK, "created_at")


# ---------------------------------------------------------------------------
# Parent and body foreign keys
# ---------------------------------------------------------------------------


def test_data_category_under_an_unknown_parent_offering_is_refused(client):
    """Declaring a data category under an offering that does not exist fails on the parent identifier.

    PRD: "Every identifier in the request path exists, resolved left to right — the corresponding 404."

    Design: Corner/entities/a_data_category_can_only_be_created_under_an_existing_parent_offering
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    response = client.create_data_category(
        UNKNOWN_OFFERING_ID, f.build_data_category_payload(), env["lead_headers"]
    )
    validate_error(response, errors.ERR_OFFERING_NOT_FOUND, 404)

    _, meta = validate_paginated(
        client.list_data_categories(env["offering_id"], env["lead_headers"])
    )
    a.assert_integer(meta["total_count"], 0, "categories on the real offering")


def test_data_category_takes_its_parent_from_the_path_and_opens_unconfirmed(client):
    """A declared data category is attached to the offering named in the path and waits unconfirmed.

    PRD: "The server attaches `offering_id` from the creation path, sets the category's `status` to `DECLARED`, and leaves `confirmed_by_user_id` null."

    Design: Corner/entities/a_data_category_can_only_be_created_under_an_existing_parent_offering
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    category = validate_success(
        client.create_data_category(
            env["offering_id"], f.build_data_category_payload(), env["lead_headers"]
        ),
        201,
    )

    assert category["offering_id"] == env["offering_id"]
    assert category["status"] == "DECLARED"
    assert category["confirmed_by_user_id"] is None

    rows, meta = validate_paginated(
        client.list_data_categories(env["offering_id"], users.ASSESSOR_HEADERS)
    )
    a.assert_integer(meta["total_count"], 1, "categories on the offering")
    assert a.ids_of(rows) == [category["id"]]


@pytest.mark.parametrize("endpoint", ["control_implementation", "engagement"])
def test_body_foreign_key_naming_no_offering_is_refused_before_any_state_gate(
    client, endpoint
):
    """A body that names an offering which does not exist fails on that reference, not on the state the endpoint demands.

    PRD: "Each unresolvable reference raises the 404 error belonging to the referenced type: `ERR_OFFERING_NOT_FOUND`, `ERR_DATA_CATEGORY_NOT_FOUND`, `ERR_BASELINE_NOT_FOUND`, `ERR_CONTROL_IMPLEMENTATION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_TEST_SLOT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_POAM_ITEM_NOT_FOUND`, `ERR_DEVIATION_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_MONITORING_PERIOD_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`, `ERR_REUSE_GRANT_NOT_FOUND` or `ERR_AGENCY_NOT_FOUND`."

    Design: Corner/entities/body_level_foreign_keys_are_resolved_before_any_business_rule
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    writes = {
        "control_implementation": lambda: client.create_control_implementation(
            f.build_control_implementation_payload(
                UNKNOWN_OFFERING_ID, control_id="AC-2", family_code="AC"
            ),
            env["lead_headers"],
        ),
        "engagement": lambda: client.create_engagement(
            f.build_engagement_payload(UNKNOWN_OFFERING_ID), env["lead_headers"]
        ),
    }

    validate_error(writes[endpoint](), errors.ERR_OFFERING_NOT_FOUND, 404)

    _, meta = validate_paginated(
        client.list_control_implementations(
            env["lead_headers"], {"offering_id": env["offering_id"]}
        )
    )
    a.assert_integer(meta["total_count"], 0, "implementations after a refused write")


def test_finding_superseding_an_unknown_item_is_refused(client):
    """A finding filed as the successor of an item that does not exist fails on that superseded reference.

    PRD: "An unresolvable `supersedes_item_id` on a new finding raises `ERR_POAM_ITEM_NOT_FOUND`."

    Design: Corner/entities/body_level_foreign_keys_are_resolved_before_any_business_rule
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    response = client.create_poam_item(
        f.build_poam_item_payload(
            env["offering_id"],
            control_id="AC-2",
            severity="LOW",
            detected_at=fx.SETUP_CLOCK,
            supersedes_item_id=UNKNOWN_POAM_ITEM_ID,
        ),
        env["lead_headers"],
    )
    validate_error(response, errors.ERR_POAM_ITEM_NOT_FOUND, 404)

    assert fx.list_poam_items(client, offering_id=env["offering_id"]) == [], (
        "a refused filing writes no finding"
    )


def test_reuse_request_naming_an_unknown_authorization_is_refused(client):
    """An agency asking to reuse an authorization that does not exist fails on that reference before the version it claims is weighed.

    PRD: "Every foreign key in the request body resolves, in the endpoint's declared field order, as do the two foreign-key filters of the offering list read — the corresponding 404."

    Design: Corner/entities/body_level_foreign_keys_are_resolved_before_any_business_rule
    """
    env = fx.seed_reference_data(client)

    response = client.create_reuse_grant(
        f.build_reuse_grant_payload(UNKNOWN_AUTHORIZATION_ID, env["agency_id"], 99),
        env["agency_headers"],
    )
    validate_error(response, errors.ERR_AUTHORIZATION_NOT_FOUND, 404)

    _, meta = validate_paginated(
        client.list_reuse_grants(users.BOARD_HEADERS, {"agency_id": env["agency_id"]})
    )
    a.assert_integer(meta["total_count"], 0, "grants after a refused request")


def test_path_selection_naming_an_unknown_sponsor_is_refused_before_the_state_gate(
    client,
):
    """Naming a sponsor agency that does not exist fails on that reference even though the offering is not yet ready to choose a path.

    PRD: "Checks are therefore evaluated in one fixed global order, and the first failing check determines the response."

    Design: Corner/entities/body_level_foreign_keys_are_resolved_before_any_business_rule
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    response = client.select_path(
        env["offering_id"],
        f.build_path_selection_payload(
            authorization_path="AGENCY_SPONSORED", sponsor_agency_id=UNKNOWN_AGENCY_ID
        ),
        env["lead_headers"],
    )
    validate_error(response, errors.ERR_AGENCY_NOT_FOUND, 404)

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "DRAFT"
    assert offering["authorization_path"] is None
    assert offering["sponsor_agency_id"] is None
    a.assert_integer(offering["version"], 1, "offering.version")


# ---------------------------------------------------------------------------
# The child read surfaces
# ---------------------------------------------------------------------------


def _findings_and_deviations(client):
    """An authorized offering carrying two self-identified findings, each with a deviation."""
    env = fx.seed_authorized_offering(client)
    env = fx.seed_poam_item(
        client,
        env,
        severity="MODERATE",
        control_id="AC-2",
        detected_at=fx.AUTHORIZATION_CLOCK,
        key="poam_moderate",
    )
    env = fx.seed_poam_item(
        client,
        env,
        severity="LOW",
        control_id="SC-7",
        detected_at=fx.AUTHORIZATION_CLOCK,
        key="poam_low",
    )
    env = fx.seed_deviation(
        client,
        env,
        env["poam_moderate_id"],
        kind="RISK_ADJUSTMENT",
        key="deviation_risk",
    )
    env = fx.seed_deviation(
        client,
        env,
        env["poam_low_id"],
        kind="FALSE_POSITIVE",
        key="deviation_false_positive",
    )
    return env


def _two_change_requests(client):
    """The same offering after one approved boundary change and one pending new-service change."""
    env = _findings_and_deviations(client)
    env = fx.seed_change_request(
        client,
        env,
        window_start="2026-04-05T00:00:00Z",
        window_end="2026-04-10T00:00:00Z",
        change_kind="BOUNDARY_CHANGE",
        decision="APPROVE",
        key="change_boundary",
    )
    env = fx.seed_change_request(
        client,
        env,
        window_start="2026-04-20T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        change_kind="NEW_SERVICE",
        added_service_count=2,
        key="change_new_service",
    )
    return env


def test_engagement_list_of_an_offering_returns_that_offering_s_own_engagement(client):
    """The engagement list nested under an offering reports the engagement attached to it and nothing else.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied."

    Design: Corner/entities/the_remaining_child_read_surfaces_list_filter_and_paginate_their_own_rows
    """
    env = fx.seed_authorized_offering(client)

    rows, meta = validate_paginated(
        client.list_offering_engagements(env["offering_id"], env["agency_headers"])
    )

    a.assert_integer(meta["total_count"], 1, "meta.total_count")
    assert meta["has_more"] is False
    assert a.ids_of(rows) == [env["engagement_id"]]
    assert rows[0]["status"] == "REPORT_DELIVERED"
    assert rows[0]["offering_id"] == env["offering_id"]


def test_engagement_read_returns_the_stored_hour_ledger_and_cost_rollup(client):
    """Reading an engagement returns the hours it contracted and the total the program priced at creation.

    PRD: "Third, `total_cost_usd` is `labor_cost_usd` plus `program_surcharge_usd` plus `hour_overage_usd`, rounded half up to two decimal places."

    Design: Corner/entities/the_remaining_child_read_surfaces_list_filter_and_paginate_their_own_rows
    """
    env = fx.seed_authorized_offering(client)

    engagement = validate_success(
        client.get_engagement(env["engagement_id"], users.BOARD_HEADERS), 200
    )

    a.assert_money(engagement["contracted_hours"], 200.00, "contracted_hours")
    a.assert_money(engagement["labor_cost_usd"], 120000.00, "labor_cost_usd")
    a.assert_money(engagement["total_cost_usd"], 127200.00, "total_cost_usd")
    a.assert_engagement_costs(engagement, 120000.00, 200.00, "MODERATE")
    a.assert_hour_conservation(engagement)


def test_deviation_read_shows_a_freshly_filed_request_waiting_for_a_queue(client):
    """A newly filed deviation request reads back submitted, unrouted and undecided, stamped with the filing lead.

    PRD: "The request opens in status `SUBMITTED` with `review_queue` null, `routed_by_user_id` and `decided_by_user_id` null, `granted_extension_days` 0, and `submitted_by_user_id` stamped from the filing lead's `X-User-ID`; the finding's `risk_disposition` moves `NONE → DEVIATION_REQUESTED` while its remediation dimension is untouched."

    Design: Corner/entities/the_remaining_child_read_surfaces_list_filter_and_paginate_their_own_rows
    """
    env = _findings_and_deviations(client)

    deviation = validate_success(
        client.get_deviation_request(
            env["deviation_false_positive_id"], users.BOARD_HEADERS
        ),
        200,
    )

    assert deviation["poam_item_id"] == env["poam_low_id"]
    assert deviation["kind"] == "FALSE_POSITIVE"
    assert deviation["status"] == "SUBMITTED"
    assert deviation["review_queue"] is None
    assert deviation["routed_by_user_id"] is None
    assert deviation["decided_by_user_id"] is None
    a.assert_integer(deviation["granted_extension_days"], 0, "granted_extension_days")
    assert deviation["submitted_by_user_id"] == users.CSP_LEAD_1

    finding = fx.read_poam_item(client, env["poam_low_id"])
    assert finding["risk_disposition"] == "DEVIATION_REQUESTED"


def test_change_request_status_filter_leaves_out_the_already_decided_request(client):
    """Filtering the change request list on the submitted status returns the pending request and drops the approved one.

    PRD: "Change requests are listed with filters on `offering_id`, `status` and `change_kind`."

    Design: Corner/entities/the_remaining_child_read_surfaces_list_filter_and_paginate_their_own_rows
    """
    env = _two_change_requests(client)

    rows, meta = validate_paginated(
        client.list_change_requests(
            env["lead_headers"],
            {"offering_id": env["offering_id"], "status": "SUBMITTED"},
        )
    )

    a.assert_integer(meta["total_count"], 1, "meta.total_count")
    assert a.ids_of(rows) == [env["change_new_service_id"]]
    assert env["change_boundary_id"] not in a.ids_of(rows), (
        "the approved request is not SUBMITTED any more"
    )


def test_change_request_list_windows_its_page_over_the_full_match_count(client):
    """A one-row window at the second offset of the change request list still reports both matching requests.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before the page window is applied."

    Design: Corner/entities/the_remaining_child_read_surfaces_list_filter_and_paginate_their_own_rows
    """
    env = _two_change_requests(client)

    rows, meta = validate_paginated(
        client.list_change_requests(
            users.BOARD_HEADERS,
            {"offering_id": env["offering_id"], "limit": 1, "offset": 1},
        )
    )

    a.assert_integer(meta["limit"], 1, "meta.limit")
    a.assert_integer(meta["offset"], 1, "meta.offset")
    a.assert_integer(meta["total_count"], 2, "meta.total_count")
    assert meta["has_more"] is False, "the window ends on the last matching row"
    assert len(rows) == 1, f"a limit of 1 returns one row, got {len(rows)}"


def test_change_request_read_reports_the_reassessment_call_for_its_kind(client):
    """A new-service change bringing two services inside the boundary needs no reassessment, while a boundary change always does.

    PRD: "The server computes `requires_reassessment` as true when the `change_kind` is `BOUNDARY_CHANGE` or when `added_service_count` is 3 or more, and false otherwise."

    Design: Corner/entities/the_remaining_child_read_surfaces_list_filter_and_paginate_their_own_rows
    """
    env = _two_change_requests(client)

    pending = validate_success(
        client.get_change_request(env["change_new_service_id"], env["agency_headers"]),
        200,
    )
    assert pending["change_kind"] == "NEW_SERVICE"
    a.assert_integer(pending["added_service_count"], 2, "added_service_count")
    assert pending["requires_reassessment"] is False
    assert pending["status"] == "SUBMITTED"

    boundary = validate_success(
        client.get_change_request(env["change_boundary_id"], env["agency_headers"]), 200
    )
    assert boundary["change_kind"] == "BOUNDARY_CHANGE"
    assert boundary["requires_reassessment"] is True


def test_finding_deadlines_follow_the_severity_allowance_from_detection(client):
    """Two findings detected on the same day fall due at different instants, each one severity allowance after detection.

    PRD: "At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days."

    Design: Corner/entities/the_remaining_child_read_surfaces_list_filter_and_paginate_their_own_rows
    """
    env = _findings_and_deviations(client)

    moderate = fx.read_poam_item(client, env["poam_moderate_id"])
    low = fx.read_poam_item(client, env["poam_low_id"])

    a.assert_instant(moderate["anchor_at"], fx.AUTHORIZATION_CLOCK, "MODERATE anchor_at")
    a.assert_instant(low["anchor_at"], fx.AUTHORIZATION_CLOCK, "LOW anchor_at")
    a.assert_instant(
        moderate["deadline_at"], "2026-06-28T00:00:00Z", "MODERATE deadline_at"
    )
    a.assert_instant(low["deadline_at"], "2026-09-26T00:00:00Z", "LOW deadline_at")
    a.assert_instant(
        moderate["deadline_at"],
        a.expected_deadline(fx.AUTHORIZATION_CLOCK, "MODERATE"),
        "MODERATE deadline_at",
    )
    a.assert_instant(
        low["deadline_at"],
        a.expected_deadline(fx.AUTHORIZATION_CLOCK, "LOW"),
        "LOW deadline_at",
    )
