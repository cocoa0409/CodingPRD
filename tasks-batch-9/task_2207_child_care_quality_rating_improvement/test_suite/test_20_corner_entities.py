"""Entity surface: creation echo, server-minted fields, schema rejection, reads and listing."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_timestamp_format,
    build_rating_spine,
    create_applied_provider,
    create_enrolled_provider,
    create_self_assessment_payload,
    create_staff_credential_payload,
    is_valid_uuid,
    make_observer_headers,
    make_provider_headers,
    open_cycle,
    score_payload,
    set_clock,
    setup_tier_one_active_spine,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

CLOCK_T0 = "2026-08-03T00:00:00Z"


def test_create_provider_returns_applied_with_echoed_inputs(api):
    """PRD §3.1: "Provider onboarding starts with an application registered by a
    `StateAdministrator`, carrying the site's `legal_name`, its `license_number`, the
    `county_code` of the licensed site, a `region_code` of `URBAN`, `RURAL`, or
    `FRONTIER` naming the reimbursement region band, a `licensed_capacity` of at least
    one child, and an `active_staff_fte` figure greater than zero with two decimal
    places representing the total full-time-equivalent count of classroom and
    administrative staff."
    PRD §3.1: "A newly registered provider begins in `APPLIED` with
    `credential_compliance_pct` at 0, `reimbursement_adjustment_cents` at 0,
    `public_listing_visible` false, `enrolled_on`, `current_rating_cycle_id` and
    `current_tier` all null, and `version` 1."

    Design: Corner/entities/create_provider_returns_applied_with_echoed_inputs
    """
    set_clock(CLOCK_T0)
    payload = {
        "legal_name": "Sunrise Center",
        "license_number": "LIC-3001",
        "county_code": "DANE",
        "region_code": "URBAN",
        "licensed_capacity": 60,
        "active_staff_fte": 1.0,
        "weekly_onsite_cap_hours": 12,
    }
    data = validate_success(api.create_provider(payload, ADMIN), 201)

    assert data["legal_name"] == "Sunrise Center", f"legal_name echo, got {data['legal_name']}"
    assert data["license_number"] == "LIC-3001", (
        f"license_number echo, got {data['license_number']}"
    )
    assert data["county_code"] == "DANE", f"county_code echo, got {data['county_code']}"
    assert data["region_code"] == "URBAN", f"region_code echo, got {data['region_code']}"
    assert data["licensed_capacity"] == 60, (
        f"licensed_capacity echo, got {data['licensed_capacity']}"
    )
    assert data["active_staff_fte"] == pytest.approx(1.00, abs=0.005), (
        f"active_staff_fte echo, got {data['active_staff_fte']}"
    )
    assert data["status"] == "APPLIED", f"a new provider must be APPLIED, got {data['status']}"


def test_provider_system_fields_are_server_minted_at_creation(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a UUID
    string with no type prefix of any kind, and a `created_at` timestamp in ISO 8601 UTC
    format with exactly three fractional digits."
    PRD §2.4: "Almost every resource additionally carries `updated_at`, formatted
    identically to `created_at` and refreshed on every mutation, and `version`, an
    integer that begins at 1 when the resource is created and increases by exactly 1 on
    every accepted mutation of that resource."
    PRD §3.1: "A newly registered provider begins in `APPLIED` with
    `credential_compliance_pct` at 0, `reimbursement_adjustment_cents` at 0,
    `public_listing_visible` false, `enrolled_on`, `current_rating_cycle_id` and
    `current_tier` all null, and `version` 1."

    Design: Corner/entities/provider_system_fields_are_server_minted_at_creation
    """
    set_clock(CLOCK_T0)
    created = create_applied_provider(legal_name="Sunrise Center", license_number="LIC-3001")
    data = validate_success(api.get_provider(created["id"], ADMIN))

    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert data["version"] == 1, f"a freshly created provider is version 1, got {data['version']}"
    assert_timestamp_format(data["created_at"])
    assert data["enrolled_on"] is None, (
        f"enrolled_on must be null while APPLIED, got {data['enrolled_on']!r}"
    )
    assert data["status"] == "APPLIED", f"status must be APPLIED, got {data['status']}"


def test_provider_computed_fields_initialised_to_unrated_posture(api):
    """PRD §3.1: "A newly registered provider begins in `APPLIED` with
    `credential_compliance_pct` at 0, `reimbursement_adjustment_cents` at 0,
    `public_listing_visible` false, `enrolled_on`, `current_rating_cycle_id` and
    `current_tier` all null, and `version` 1."

    Design: Corner/entities/provider_computed_fields_initialised_to_unrated_posture
    """
    set_clock(CLOCK_T0)
    created = create_applied_provider(legal_name="Sunrise Center", license_number="LIC-3001")
    data = validate_success(api.get_provider(created["id"], ADMIN))

    assert data["current_rating_cycle_id"] is None, (
        f"current_rating_cycle_id must be null, got {data['current_rating_cycle_id']!r}"
    )
    assert data["current_tier"] is None, (
        f"current_tier must be null, got {data['current_tier']!r}"
    )
    assert data["credential_compliance_pct"] == pytest.approx(0.00, abs=0.005), (
        f"credential_compliance_pct must start at 0.00, got {data['credential_compliance_pct']}"
    )
    assert data["reimbursement_adjustment_cents"] == 0, (
        f"reimbursement_adjustment_cents must start at 0, got "
        f"{data['reimbursement_adjustment_cents']}"
    )
    assert data["public_listing_visible"] is False, (
        f"public_listing_visible must start false, got {data['public_listing_visible']!r}"
    )


def test_provider_weekly_onsite_cap_hours_default_twelve(api):
    """PRD §3.1: "An optional `weekly_onsite_cap_hours` value, greater than zero with one
    decimal place, sets how many on-site coaching hours the site is willing to host in
    any ISO calendar week and defaults to 12 when omitted."

    Design: Corner/entities/provider_weekly_onsite_cap_hours_default_twelve
    """
    set_clock(CLOCK_T0)
    payload = {
        "legal_name": "Default Cap Center",
        "license_number": "LIC-3002",
        "county_code": "DANE",
        "region_code": "RURAL",
        "licensed_capacity": 30,
        "active_staff_fte": 2.0,
    }
    data = validate_success(api.create_provider(payload, ADMIN), 201)

    assert data["weekly_onsite_cap_hours"] == pytest.approx(12, abs=0.005), (
        f"omitted weekly_onsite_cap_hours must default to 12, got "
        f"{data['weekly_onsite_cap_hours']}"
    )


def test_create_provider_missing_license_number_rejected(api):
    """PRD §2.7: "Sixth, body schema and range checking on every creating or acting
    request produces `ERR_VALIDATION` with HTTP 422: required fields must be present,
    enum-typed fields must carry a declared member, integers must respect their declared
    minimums, a subscale score must lie between 1.0 and 7.0 inclusive and sit exactly on
    a half-point step, weights and fractional shares must lie inside their declared
    bounds, a service month must match the four-digit-year-hyphen-two-digit-month form, a
    secondary observer must differ from the lead observer, child-day maps may carry only
    the three declared age-band keys, and a claimed-points map must supply all five
    domain codes with no value above that domain's point ceiling."

    Design: Corner/entities/create_provider_missing_license_number_rejected
    """
    set_clock(CLOCK_T0)
    payload = {
        "legal_name": "No License Center",
        "county_code": "DANE",
        "region_code": "URBAN",
        "licensed_capacity": 30,
        "active_staff_fte": 1.0,
    }
    validate_error(api.create_provider(payload, ADMIN), "ERR_VALIDATION", 422)

    rows, meta = validate_paginated(api.list_providers(ADMIN))
    assert meta["total_count"] == 0, (
        f"a rejected application must persist no Provider, got total_count "
        f"{meta['total_count']}"
    )
    assert rows == [], f"provider collection must stay empty, got {rows}"


def test_create_provider_region_code_outside_enum_rejected(api):
    """PRD §3.1: "Provider onboarding starts with an application registered by a
    `StateAdministrator`, carrying the site's `legal_name`, its `license_number`, the
    `county_code` of the licensed site, a `region_code` of `URBAN`, `RURAL`, or
    `FRONTIER` naming the reimbursement region band, a `licensed_capacity` of at least
    one child, and an `active_staff_fte` figure greater than zero with two decimal
    places representing the total full-time-equivalent count of classroom and
    administrative staff."
    PRD §2.7: "Sixth, body schema and range checking on every creating or acting request
    produces `ERR_VALIDATION` with HTTP 422: required fields must be present, enum-typed
    fields must carry a declared member, integers must respect their declared minimums, a
    subscale score must lie between 1.0 and 7.0 inclusive and sit exactly on a half-point
    step, weights and fractional shares must lie inside their declared bounds, a service
    month must match the four-digit-year-hyphen-two-digit-month form, a secondary
    observer must differ from the lead observer, child-day maps may carry only the three
    declared age-band keys, and a claimed-points map must supply all five domain codes
    with no value above that domain's point ceiling."

    Design: Corner/entities/create_provider_region_code_outside_enum_rejected
    """
    set_clock(CLOCK_T0)
    payload = {
        "legal_name": "Bad Region Center",
        "license_number": "LIC-3003",
        "county_code": "DANE",
        "region_code": "SUBURBAN",
        "licensed_capacity": 30,
        "active_staff_fte": 1.0,
    }
    validate_error(api.create_provider(payload, ADMIN), "ERR_VALIDATION", 422)

    rows, meta = validate_paginated(api.list_providers(ADMIN))
    assert meta["total_count"] == 0, (
        f"an out-of-enum region_code must store nothing, got total_count "
        f"{meta['total_count']}"
    )
    assert rows == [], f"provider collection must stay empty, got {rows}"


def test_staff_credential_level_above_six_rejected(api):
    """PRD §3.2: "Either the provider itself or a `StateAdministrator` registers a staff
    member by supplying that person's `staff_registry_id` — the identifier the professional
    development registry knows them by, which must be unique within the provider and
    otherwise raises `ERR_DUPLICATE_RESOURCE` — a `role_type` of `DIRECTOR`,
    `LEAD_TEACHER`, or `ASSISTANT`, a `credential_level` from 1 to 6, and an `fte` share
    greater than 0 and no greater than 1 with two decimal places."
    PRD §2.7: "Sixth, body schema and range checking on every creating or acting request
    produces `ERR_VALIDATION` with HTTP 422: required fields must be present, enum-typed
    fields must carry a declared member, integers must respect their declared minimums, a
    subscale score must lie between 1.0 and 7.0 inclusive and sit exactly on a half-point
    step, weights and fractional shares must lie inside their declared bounds, a service
    month must match the four-digit-year-hyphen-two-digit-month form, a secondary
    observer must differ from the lead observer, child-day maps may carry only the three
    declared age-band keys, and a claimed-points map must supply all five domain codes
    with no value above that domain's point ceiling."

    Design: Corner/entities/staff_credential_level_above_six_rejected
    """
    set_clock(CLOCK_T0)
    provider = create_enrolled_provider(legal_name="Level Seven Center")
    payload = create_staff_credential_payload(role_type="DIRECTOR", credential_level=7, fte=1.00)

    validate_error(
        api.create_staff_credential(provider["id"], payload, ADMIN), "ERR_VALIDATION", 422
    )

    rows, meta = validate_paginated(
        api.list_staff_credentials(ADMIN, params={"provider_id": provider["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a level-7 credential must not persist, got total_count {meta['total_count']}"
    )
    assert rows == [], f"credential collection must stay empty, got {rows}"

    refreshed = validate_success(api.get_provider(provider["id"], ADMIN))
    assert refreshed["credential_compliance_pct"] == pytest.approx(0.00, abs=0.005), (
        "a rejected credential must leave credential_compliance_pct at 0.00, got "
        f"{refreshed['credential_compliance_pct']}"
    )


def test_get_provider_unknown_id_returns_provider_not_found(api):
    """PRD §2.6: "An unresolvable `provider_id` yields `ERR_PROVIDER_NOT_FOUND`."
    PRD §2.6: "All six carry HTTP status 404."

    Design: Corner/entities/get_provider_unknown_id_returns_provider_not_found
    """
    set_clock(CLOCK_T0)
    validate_error(
        api.get_provider(NON_EXISTENT_UUID, ADMIN), "ERR_PROVIDER_NOT_FOUND", 404
    )


def test_list_providers_pagination_reports_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` object of a list response carries `limit` (the effective page
    size), `offset` (the effective starting position), `total_count` (the number of
    records matching the filters before pagination), and `has_more` (true when records
    remain beyond the current page)."

    Design: Corner/entities/list_providers_pagination_reports_total_count_and_has_more
    """
    set_clock(CLOCK_T0)
    create_applied_provider(legal_name="Alpha Center", license_number="LIC-3101")
    create_applied_provider(legal_name="Bravo Center", license_number="LIC-3102")
    create_applied_provider(legal_name="Charlie Center", license_number="LIC-3103")

    first_rows, first_meta = validate_paginated(
        api.list_providers(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2, f"limit=2 must return 2 rows, got {len(first_rows)}"
    assert first_meta["limit"] == 2, f"effective limit must be 2, got {first_meta['limit']}"
    assert first_meta["offset"] == 0, f"effective offset must be 0, got {first_meta['offset']}"
    assert first_meta["total_count"] == 3, (
        f"total_count counts all matching records before pagination, got "
        f"{first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        f"one record remains beyond page one, so has_more must be true, got "
        f"{first_meta['has_more']}"
    )

    second_rows, second_meta = validate_paginated(
        api.list_providers(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, f"the tail page holds 1 row, got {len(second_rows)}"
    assert second_meta["offset"] == 2, f"effective offset must be 2, got {second_meta['offset']}"
    assert second_meta["total_count"] == 3, (
        f"total_count is unaffected by the offset, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        f"nothing remains beyond the tail page, got {second_meta['has_more']}"
    )


def test_observation_score_is_append_only_with_no_version_field(api):
    """PRD §2.4: "An observation score attempt carries only `id` and `created_at`: it has
    no `updated_at` and no `version`, because score rows are append-only. A correction to a
    subscale score never edits an existing row; it appends a new row and demotes the
    previous one."
    PRD §3.4: "Scores are append-only: a submission records a new row whose
    `observation_visit_id` names the visit, whose `observer_id` names the acting observer,
    whose `attempt_no` is one greater than the highest attempt already recorded for that
    combination of visit, observer, and subscale, and whose `is_current` flag is true; the
    previously current row for that same combination has its `is_current` set to false. The
    first attempt for a combination carries `attempt_no` 1."

    Design: Corner/entities/observation_score_is_append_only_with_no_version_field
    """
    ctx = build_rating_spine(stop_at="OBSERVATION_SCHEDULED")
    visit_id = ctx["visit"]["id"]
    observer_headers = make_observer_headers(ctx["lead"]["id"])
    set_clock("2026-08-06T09:00:00Z")

    first = validate_success(
        api.submit_score(visit_id, score_payload("SPACE_FURNISHINGS", 4.0), observer_headers), 201
    )
    assert first["attempt_no"] == 1, f"the first attempt carries attempt_no 1, got {first['attempt_no']}"
    assert first["is_current"] is True, f"the first attempt is current, got {first['is_current']}"

    second = validate_success(
        api.submit_score(visit_id, score_payload("SPACE_FURNISHINGS", 6.0), observer_headers), 201
    )
    assert second["id"] != first["id"], "a correction must append a new row, not edit the old one"
    assert second["attempt_no"] == 2, (
        f"the correction's attempt_no must be 2, got {second['attempt_no']}"
    )
    assert second["is_current"] is True, (
        f"the newest row is current, got {second['is_current']}"
    )
    assert "version" not in second, (
        f"a score row has no version field, got keys {sorted(second.keys())}"
    )
    assert "updated_at" not in second, (
        f"a score row has no updated_at field, got keys {sorted(second.keys())}"
    )

    demoted = validate_success(api.get_observation_score(first["id"], ADMIN))
    assert demoted["is_current"] is False, (
        f"the previously current row must be demoted, got {demoted['is_current']}"
    )
    assert demoted["attempt_no"] == 1, (
        f"the demoted row keeps attempt_no 1, got {demoted['attempt_no']}"
    )
    assert demoted["raw_score"] == pytest.approx(4.0, abs=0.005), (
        f"the demoted row keeps its original raw_score of 4.0, got {demoted['raw_score']}"
    )
    assert "version" not in demoted, (
        f"a score row has no version field, got keys {sorted(demoted.keys())}"
    )

    rows, meta = validate_paginated(
        api.list_observation_scores(
            ADMIN,
            params={"observation_visit_id": visit_id, "subscale_code": "SPACE_FURNISHINGS"},
        )
    )
    assert meta["total_count"] == 2, (
        f"both attempts must remain stored, got total_count {meta['total_count']}"
    )
    assert len(rows) == 2, f"both attempts must be listed, got {len(rows)}"


def test_self_assessment_under_unknown_cycle_returns_rating_artifact_not_found(api):
    """PRD §2.6: "An unresolvable `rating_cycle_id`, `self_assessment_id`,
    `observation_visit_id`, or `observation_score_id` — whether it arrived in the path or in
    a request body — yields `ERR_RATING_ARTIFACT_NOT_FOUND`."
    PRD §2.6: "All six carry HTTP status 404."
    PRD §2.7: "Third, path existence: every path-templated resource must resolve, left to
    right, producing one of the 404 family codes described above."

    Design: Corner/entities/self_assessment_under_unknown_cycle_returns_rating_artifact_not_found
    """
    set_clock(CLOCK_T0)
    provider = create_enrolled_provider(legal_name="Orphan Assessment Center")

    validate_error(
        api.create_self_assessment(
            NON_EXISTENT_UUID,
            create_self_assessment_payload(),
            make_provider_headers(provider["id"]),
        ),
        "ERR_RATING_ARTIFACT_NOT_FOUND",
        404,
    )

    rows, meta = validate_paginated(api.list_self_assessments(ADMIN))
    assert meta["total_count"] == 0, (
        f"no self-assessment may be persisted under an unknown cycle, got total_count "
        f"{meta['total_count']}"
    )
    assert rows == [], f"self-assessment collection must stay empty, got {rows}"


def test_rating_cycle_read_exposes_hybrid_cross_spine_links(api):
    """PRD §3.3: "A cycle that passes those gates is created in `DRAFT` with `opened_on`
    stamped from the logical clock, with `provider_id` recording the owning provider, and
    with `supersedes_cycle_id` pointed at the provider's currently active cycle when one
    exists and left null when this is the provider's first cycle."
    PRD §3.3: "Cycles may be listed and narrowed by `provider_id`, by `status`, by
    `publication_status`, by `supersedes_cycle_id`, or by `superseded_by_cycle_id`, and read
    individually together with their point maps, block clearance, tier and validity fields."
    PRD §3.5: "The provider's `current_rating_cycle_id` and `current_tier` are repointed at
    the new cycle, which is also what carries a first-time provider from `ENROLLED` to
    `ACTIVE`."

    Design: Corner/entities/rating_cycle_read_exposes_hybrid_cross_spine_links
    """
    ctx = setup_tier_one_active_spine()
    provider_id = ctx["provider"]["id"]
    first_cycle_id = ctx["cycle"]["id"]

    set_clock("2028-06-02T00:00:00Z")
    second = open_cycle(provider_id, "RERATING")

    assert second["cycle_type"] == "RERATING", (
        f"the second cycle is a RERATING cycle, got {second['cycle_type']}"
    )
    assert second["status"] == "DRAFT", f"a new cycle starts in DRAFT, got {second['status']}"
    assert second["provider_id"] == provider_id, (
        f"provider_id must record the owning provider, got {second['provider_id']}"
    )
    assert second["supersedes_cycle_id"] == first_cycle_id, (
        "supersedes_cycle_id must point at the currently active cycle, got "
        f"{second['supersedes_cycle_id']}"
    )

    first = validate_success(api.get_rating_cycle(first_cycle_id, ADMIN))
    assert first["status"] == "ACTIVE", (
        f"opening a successor does not disturb the active cycle, got {first['status']}"
    )
    assert first["superseded_by_cycle_id"] is None, (
        "superseded_by_cycle_id stays null until the successor takes effect, got "
        f"{first['superseded_by_cycle_id']}"
    )

    provider = validate_success(api.get_provider(provider_id, ADMIN))
    assert provider["current_rating_cycle_id"] == first_cycle_id, (
        "the provider still points at the active cycle, got "
        f"{provider['current_rating_cycle_id']}"
    )
    assert provider["current_tier"] == 1, (
        f"the provider keeps its awarded tier of 1, got {provider['current_tier']}"
    )

    rows, meta = validate_paginated(
        api.list_rating_cycles(ADMIN, params={"supersedes_cycle_id": first_cycle_id})
    )
    assert meta["total_count"] == 1, (
        f"exactly one cycle supersedes the first, got total_count {meta['total_count']}"
    )
    assert rows[0]["id"] == second["id"], (
        f"the supersedes_cycle_id filter must return the successor, got {rows[0]['id']}"
    )
