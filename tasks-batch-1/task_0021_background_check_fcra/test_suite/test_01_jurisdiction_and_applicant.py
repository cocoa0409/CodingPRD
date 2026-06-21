"""Corner: Jurisdiction creation defaults, Applicant creation system fields,
Application retrieval/list, state_code shape, not-found.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID, ApiErrorId,
    TEST_USERS,
    create_jurisdiction_payload, create_applicant_payload, create_application_payload,
    set_clock, create_jurisdiction, create_applicant, create_application,
    make_applicant_headers, PA, REC,
)


def test_jurisdiction_create_omits_optional_fields_defaults_apply(api):
    """Creating a Jurisdiction with only state_code applies the documented
    defaults: ban_the_box_enabled=false, salary_history_ban_enabled=false,
    pre_adverse_waiting_days=5.

    PRD §3.1: "Each US-state `Jurisdiction` is created by a `PlatformAdmin`
    from a `state_code` (a two-letter uppercase US state code, unique across
    jurisdictions, with length exactly two), a `ban_the_box_enabled` boolean
    (default false; when true, criminal history may not be inquired about
    before a conditional offer), a `salary_history_ban_enabled` boolean
    (default false; when true, `salary_history_disclosed` on an Application
    must remain null at submission), and `pre_adverse_waiting_days` (an
    integer, default 5, that must be at least 5 — the FCRA federal floor;
    lower values are rejected with `ERR_BELOW_FEDERAL_FLOOR`)."

    Design: Corner/entities/jurisdiction_create_returns_201_with_default_flags
    """
    set_clock("2026-06-01T10:00:00.000Z")
    resp = api.create_jurisdiction(
        create_jurisdiction_payload(state_code="TX"), PA,
    )
    jur = validate_success(resp, 201)
    assert jur["ban_the_box_enabled"] is False, \
        f"ban_the_box_enabled default must be false, got {jur['ban_the_box_enabled']!r}"
    assert jur["salary_history_ban_enabled"] is False, \
        f"salary_history_ban_enabled default must be false, got {jur['salary_history_ban_enabled']!r}"
    assert jur["pre_adverse_waiting_days"] == 5, \
        f"pre_adverse_waiting_days default must be 5, got {jur['pre_adverse_waiting_days']!r}"


def test_applicant_create_returns_system_minted_id_and_created_at(api):
    """A successful POST /applicants returns an Applicant with system-minted
    UUID id and the server-stamped created_at timestamp (which is read from
    the SystemClock, not OS time), plus version starting at 1.

    PRD §2.4: "Every business resource — Applicant, Application,
    ConsentDisclosure, BackgroundCheckOrder, Verification, and AdverseAction
    — carries four system-managed fields. The `id` is a server-minted UUID,
    with no type prefix and no embedded semantics. The `created_at` is an
    ISO 8601 UTC timestamp recorded at insertion time with three fractional
    digits. The `updated_at` is an ISO 8601 UTC timestamp with three
    fractional digits, refreshed on every mutation. The `version` is an
    integer that starts at 1 on creation and increments by one on every
    mutation; it is the value clients carry forward to drive optimistic
    concurrency control."

    Design: Corner/entities/applicant_create_returns_201_with_system_id_and_timestamps
    """
    set_clock("2026-06-01T10:00:00.000Z")
    resp = api.create_applicant(
        create_applicant_payload(
            full_name="Alan Kay",
            email="alan.kay@example.com",
            date_of_birth="1940-05-17T00:00:00.000Z",
        ),
        TEST_USERS["applicant_headers"],
    )
    a = validate_success(resp, 201)
    assert a["id"], "system must mint an id"
    assert a["created_at"] == "2026-06-01T10:00:00.000Z", \
        f"created_at must be stamped from the SystemClock, got {a['created_at']!r}"
    assert a["version"] == 1, f"version must start at 1, got {a['version']!r}"


def test_get_application_by_id_returns_stored_record(api):
    """GET /api/v1/applications/{id} returns the persisted Application
    including the DRAFT status it started in and the position_title that
    was supplied.

    PRD §3.1: "With an applicant in hand, an `Application` is opened by
    supplying `applicant_id`, `jurisdiction_id`, and a `position_title` for
    the role being applied to. The application begins in `DRAFT`."

    Design: Corner/entities/get_application_by_id_returns_stored_record
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="OR")
    applicant = create_applicant(full_name="Sue Black", email="sue@example.com",
                                 date_of_birth="1970-01-01T00:00:00.000Z")
    app = create_application(applicant["id"], jur["id"], position_title="Engineer")
    resp = api.get_application(app["id"], make_applicant_headers(applicant["id"]))
    got = validate_success(resp, 200)
    assert got["id"] == app["id"]
    assert got["status"] == "DRAFT", f"new application must be DRAFT, got {got['status']!r}"
    assert got["position_title"] == "Engineer"


def test_list_applications_returns_array_response_with_pagination_meta(api):
    """GET /api/v1/applications returns an array envelope with pagination
    metadata (limit, offset, total_count, has_more).

    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.3: "The `meta` envelope for list responses includes `limit`,
    `offset`, `total_count` (the total number of rows matching the filter),
    and `has_more` (true when more rows exist past the current page)."

    Design: Corner/entities/list_applications_with_pagination_envelope
    """
    set_clock("2026-06-01T10:00:00.000Z")
    jur = create_jurisdiction(state_code="TN")
    applicant = create_applicant(full_name="Mae Jemison", email="mae@example.com",
                                 date_of_birth="1956-10-17T00:00:00.000Z")
    create_application(applicant["id"], jur["id"], position_title="Engineer")
    create_application(applicant["id"], jur["id"], position_title="Manager")
    resp = api.list_applications(REC)
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert len(data) >= 2, f"expected at least 2 applications, got {len(data)}"
    for k in ("limit", "offset", "total_count", "has_more"):
        assert k in meta, f"pagination meta must carry {k}"


def test_get_application_with_non_existent_uuid_returns_404(api):
    """Looking up a non-existent application returns ERR_NOT_FOUND.

    PRD §2.9: "Then every id referenced in the URL path and every foreign
    key in the body must resolve (otherwise `ERR_NOT_FOUND`)."

    Design: Corner/entities/get_application_not_found_returns_404
    """
    set_clock("2026-06-01T10:00:00.000Z")
    resp = api.get_application(NON_EXISTENT_UUID, REC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_jurisdiction_state_code_lowercase_rejected_as_invalid_request(api):
    """state_code must be a two-letter uppercase US state code; a lowercase
    value is malformed per the type constraint, and PRD §2.9 step 8 maps
    body-shape failures to ERR_INVALID_REQUEST.

    PRD §3.1: "Each US-state `Jurisdiction` is created by a `PlatformAdmin`
    from a `state_code` (a two-letter uppercase US state code, unique across
    jurisdictions, with length exactly two)"
    PRD §2.9: "Body schema well-formedness — types, enum membership, and
    presence of required fields — is checked last and rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/jurisdiction_state_code_enum_uppercase_only
    """
    set_clock("2026-06-01T10:00:00.000Z")
    resp = api.create_jurisdiction({"state_code": "ca"}, PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
