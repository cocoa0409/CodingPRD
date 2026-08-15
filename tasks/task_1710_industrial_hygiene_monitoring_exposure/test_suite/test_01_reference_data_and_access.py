"""Reference data, response envelope, header auth, and RBAC (PRD §2, §3.1, §4)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_exposure_limit,
    assert_pump,
    assert_site,
    create_limit_payload,
    create_pump_payload,
    is_valid_uuid,
    make_employee_headers,
    make_lab_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["firm_admin_headers"]
IH = TEST_USERS["ih_headers"]
TECH = TEST_USERS["tech_headers"]


def test_site_creation_defaults_and_envelope(api):
    """PRD §3.1: "when omitted, `retention_years` defaults to 30, and it must
    be at least 1."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/site_creation_defaults_and_envelope
    """
    res = api.create_site(
        {"name": "Apex Coating", "industry_code": "332812"}, ADMIN
    )
    assert isinstance(res.json().get("meta", {}).get("api_request_id"), str)
    assert isinstance(res.json()["meta"].get("api_request_timestamp"), str)
    assert res.json()["response_type"] == "object"
    site = validate_success(res, 201)
    assert_site(site)
    assert site["retention_years"] == 30, "default retention_years must be 30"
    assert is_valid_uuid(site["id"])
    assert isinstance(site["version"], int) and site["version"] >= 1


def test_employee_missing_required_field_rejected(api):
    """PRD §2.8: "Third, request-body schema: required fields must be present —
    including the conditional rules that a `PERSONAL` sample requires
    `employee_id`, `pump_id`, and `pre_calibration_id` while a `FIELD_BLANK`
    forbids all three, and that a `PPE_RESPIRATOR` control requires
    `assigned_protection_factor` while any other control type forbids it —
    enum values must be drawn from their declared sets, numeric ranges must be
    respected, and an end date may not precede its start date on either a plan
    window or a batch window; failures surface as `ERR_INVALID_REQUEST` or
    `ERR_INVALID_DATE_RANGE`."
    PRD §3.1: "Employees are registered at a site with a `site_id` naming the
    employing site, the worker's `full_name`, an `external_ref` carrying the
    client-side employee number — unique per site — and a `job_title`".

    Design: Corner/entities/employee_missing_required_field_rejected
    """
    site = fx.create_site(name="Apex Coating")
    res = api.create_employee(
        {"site_id": site["id"], "external_ref": "E1", "job_title": "Painter"},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_limit_unique_key_duplicate_rejected(api):
    """PRD §3.1: "A registered limit carries a system-enforced `uniqueness`
    constraint on the triple of `analyte_code`, `basis`, and `limit_type`:
    registering a second limit with the same triple is rejected with
    `ERR_DUPLICATE_LIMIT` (409)."

    Design: Corner/entities/limit_unique_key_duplicate_rejected
    """
    first = validate_success(
        api.create_exposure_limit(create_limit_payload(), ADMIN), 201
    )
    assert_exposure_limit(first)

    dup = api.create_exposure_limit(create_limit_payload(), ADMIN)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_LIMIT)

    other_basis = validate_success(
        api.create_exposure_limit(
            create_limit_payload(basis="ACGIH_TLV", limit_mg_m3=0.025), ADMIN
        ),
        201,
    )
    assert other_basis["basis"] == "ACGIH_TLV"


def test_pump_serial_unique_per_site(api):
    """PRD §3.1: "Sampling pumps are registered per site with a `site_id` and
    a `serial_number`; the serial must be unique within its site, and a
    duplicate registration is rejected with `ERR_DUPLICATE_PUMP_SERIAL` (409)."

    Design: Corner/entities/pump_serial_unique_per_site
    """
    site1 = fx.create_site(name="Site 1")
    site2 = fx.create_site(name="Site 2", industry_code="332710")
    pump1 = validate_success(
        api.create_pump(
            create_pump_payload(site1["id"], serial_number="P-001"), ADMIN
        ),
        201,
    )
    assert_pump(pump1)

    dup = api.create_pump(
        create_pump_payload(site1["id"], serial_number="P-001"), ADMIN
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_PUMP_SERIAL)

    other_site = validate_success(
        api.create_pump(
            create_pump_payload(site2["id"], serial_number="P-001"), ADMIN
        ),
        201,
    )
    assert other_site["site_id"] == site2["id"]


def test_not_found_and_error_envelope(api):
    """PRD §2.8: "Fourth, existence: path identifiers are resolved left to
    right, then body-referenced identifiers in their declared input order; the
    first identifier that does not correspond to an existing resource yields
    `ERR_NOT_FOUND`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/entities/not_found_and_error_envelope
    """
    res = api.get_seg(NON_EXISTENT_UUID, IH)
    assert res.status_code == 404
    assert res.json()["response_type"] == "error"
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value
    in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (400)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    res = api.list_sites(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    # Empty value is equally rejected; a role header alone is not enough.
    res2 = api.list_sites(headers={"X-User-ID": "", "X-User-Role": "FirmAdmin"})
    validate_error(res2, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_rbac_matrix_enforcement(api):
    """PRD §2.1: "If the named role is not authorized for the target operation,
    the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403)."
    PRD §2.8: "Second, role authorization: the declared role must be permitted
    on the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §2.1: "All seven roles may use every read operation; write operations
    are restricted as enumerated in §4."

    Design: Corner/rbac/rbac_matrix_enforcement
    """
    site = fx.create_site(name="Apex Coating")
    employee_actor = make_employee_headers("44444444-4444-4444-4444-444444444444")

    # Employee creating a SEG (§4: IndustrialHygienist only).
    res1 = api.create_seg(
        {
            "site_id": site["id"],
            "name": "X",
            "analyte_code": "PB",
            "exposure_limit_id": "33333333-3333-3333-3333-333333333333",
            "task_description": "t",
        },
        employee_actor,
    )
    validate_error(res1, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    # FieldTechnician entering a lab result (§4: LabAnalyst only).
    res2 = api.create_lab_result(
        {
            "field_sample_id": "55555555-5555-5555-5555-555555555555",
            "lab_batch_id": "66666666-6666-6666-6666-666666666666",
            "mass_ug": 5,
        },
        TECH,
    )
    validate_error(res2, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    # LabAnalyst approving a plan (§4: CIHDirector only); the role check fires
    # before the nonexistent plan id is ever resolved.
    res3 = api.approve_plan(
        "77777777-7777-7777-7777-777777777777",
        make_lab_headers("u_lab_1"),
    )
    validate_error(res3, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    # IndustrialHygienist driving the clock (§4: FirmAdmin only).
    res4 = api.set_clock("2026-08-10T00:00:00Z", IH)
    validate_error(res4, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    # IndustrialHygienist acknowledging a notification (§4: Employee only).
    res5 = api.acknowledge_notification(
        "88888888-8888-8888-8888-888888888888", IH
    )
    validate_error(res5, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    # Shared read: Employee lists sites and sees the one just created.
    rows = validate_success(api.list_sites(employee_actor), 200)
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["id"] == site["id"]


def test_envelope_pagination_and_immediate_visibility(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10, must be at least 1, and may not exceed 100. The `offset`
    parameter skips that many items from the start of the result set and
    defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/envelope_pagination_and_immediate_visibility
    """
    site1 = fx.create_site(name="Site 1")
    site2 = fx.create_site(name="Site 2", industry_code="332710")

    page1_res = api.list_sites(ADMIN, params={"limit": 1, "offset": 0})
    assert page1_res.json()["response_type"] == "array"
    page1, meta1 = validate_paginated(page1_res)
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1 and meta1["offset"] == 0
    assert len(page1) == 1

    page2, meta2 = validate_paginated(
        api.list_sites(ADMIN, params={"limit": 1, "offset": 1})
    )
    assert meta2["has_more"] is False
    assert len(page2) == 1

    # Both just-created rows are visible immediately across the two pages.
    assert {page1[0]["id"], page2[0]["id"]} == {site1["id"], site2["id"]}


def test_empty_database_list_envelope(api):
    """PRD §2.2: "The `data` field contains the resource object or an array of
    resource objects."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/errors/all_errors_triggerable
    """
    res = api.list_sites(ADMIN)
    assert res.json()["response_type"] == "array"
    rows, meta = validate_paginated(res)
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
