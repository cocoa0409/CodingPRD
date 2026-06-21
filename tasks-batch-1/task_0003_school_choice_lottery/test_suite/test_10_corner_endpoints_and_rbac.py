"""Corner-coverage tests for endpoint envelope behavior (PRD §2.2, §2.3, §2.4)
and role-based access control (PRD §2.1, §4).
"""
from test_helpers import (
    set_clock,
    create_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    create_application,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    make_unauthenticated_headers,
    validate_success,
    validate_paginated,
    validate_error,
    ApiErrorId,
)
from test_helpers.factories import (
    create_district_payload,
    create_school_payload,
)


# =====================================================================
# Corner / endpoints — list schools returns paginated envelope
# =====================================================================

def test_list_schools_pagination_envelope_present(api):
    """PRD §2.3: "All list endpoints accept two query parameters that govern
    pagination: `limit` and `offset`. ... The `meta` block of every list
    response carries `limit`, `offset`, `total_count` (the total number of
    rows matching the query, ignoring pagination), and `has_more` (a boolean
    indicating whether further pages exist beyond the current one)."

    Design: Corner/endpoints/list_schools_pagination_envelope_present
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DPG", name="Pg", poverty_index_pct=0.00)
    for i in range(3):
        create_school(district["id"], code=f"PG{i+1}", name=f"P{i+1}",
                      school_type="MAGNET", grade_min=0, grade_max=5,
                      total_seats=1)
    res = api.list_schools(
        TEST_USERS["district_admin_headers"],
        params={"district_id": district["id"], "limit": 2, "offset": 0},
    )
    data, meta = validate_paginated(res)
    assert len(data) == 2, (
        f"limit=2 must return exactly 2 schools; got {len(data)}"
    )
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3, (
        f"total_count must reflect all matching rows ignoring pagination; "
        f"got {meta['total_count']!r}"
    )
    assert meta["has_more"] is True, (
        f"3 total / limit 2 / offset 0 must have has_more=true; "
        f"got {meta['has_more']!r}"
    )


# =====================================================================
# Corner / endpoints — PATCH /schools/{id} increments version by 1
# =====================================================================

def test_patch_school_increments_version_by_one(api):
    """PRD §2.4: "The `version` field is an integer that begins at 1 on
    creation and increments by exactly one each time the row is mutated;
    it is the parent token consulted by optimistic concurrency control."
    PRD §3.1: "A subsequent patch can update the school's `name` or
    `total_seats`; `total_seats` below zero is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/patch_school_increments_version
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DPS", name="Ps", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SPS", name="Ps",
                           school_type="MAGNET", grade_min=0, grade_max=5,
                           total_seats=5)
    v0 = school["version"]
    res = api.update_school(
        school["id"], {"name": "Ps Renamed"},
        TEST_USERS["district_admin_headers"],
    )
    data = validate_success(res, 200)
    assert data["version"] == v0 + 1, (
        f"PATCH must increment version by exactly one; expected {v0+1}, "
        f"got {data['version']!r}"
    )
    assert data["name"] == "Ps Renamed"


# =====================================================================
# Corner / rbac — Guardian cannot create a district
# =====================================================================

def test_guardian_cannot_create_district_returns_forbidden(api):
    """PRD §2.1: "A request whose headers are well-formed but whose role is
    not permitted to perform the requested operation is rejected with
    `ERR_FORBIDDEN` and HTTP 403."

    POST /lottery/districts is an exclusive DistrictAdmin operation (PRD
    §4 endpoint table). A Guardian attempting it must be rejected with
    ERR_FORBIDDEN.

    Design: Corner/rbac/guardian_cannot_create_district
    """
    set_clock("2026-01-01T00:00:00Z")
    seed_district = create_district(code="DRB", name="Rb", poverty_index_pct=0.00)
    family = register_family(seed_district["id"], guardian_email="rb@x.com",
                             residence_zone_code="ZRB", poverty_flag=False)
    payload = create_district_payload(code="DRBX", name="RbX",
                                      poverty_index_pct=5.00)
    res = api.create_district(payload, make_guardian_headers(family["id"]))
    err = validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
    assert err["error_id"] == ApiErrorId.ERR_FORBIDDEN.value


# =====================================================================
# Corner / rbac — DistrictAdmin can list applications (shared GET)
# =====================================================================

def test_district_admin_can_list_applications_shared_operation(api):
    """PRD §4 endpoint table: "GET /lottery/applications | List applications;
    filterable by window, student, school, status. | `DistrictAdmin`,
    `Guardian`."

    The endpoint is shared by both roles. A DistrictAdmin call to
    GET /lottery/applications must return 200 with the standard paginated
    envelope and a data array containing the just-created application.

    Design: Corner/rbac/district_admin_can_perform_all_shared_operations
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DSS", name="Ss", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SSS", name="Sss",
                           school_type="MAGNET", grade_min=0, grade_max=5,
                           total_seats=1)
    window = create_window(district["id"], cycle_label="2026-27-SS")
    family = register_family(district["id"], guardian_email="ss@x.com",
                             residence_zone_code="ZSS", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=3)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    app = create_application(family["id"], window["id"], student["id"],
                             school["id"], choice_rank=1)
    res = api.list_applications(
        TEST_USERS["district_admin_headers"],
        params={"window_id": window["id"]},
    )
    data, _meta = validate_paginated(res)
    ids = [item["id"] for item in data]
    assert app["id"] in ids, (
        f"DistrictAdmin's list must include just-created application "
        f"{app['id']!r}; got ids={ids}"
    )


# =====================================================================
# Corner / rbac — missing auth headers → ERR_UNAUTHENTICATED
# =====================================================================

def test_unauthenticated_request_returns_401(api):
    """PRD §2.1: "Every request to the API — except the public
    family-registration endpoint, which is callable anonymously — must
    carry two HTTP headers identifying the caller: `X-User-ID` (an opaque
    string identifier for the acting principal) and `X-User-Role` (the
    string name of the role being asserted). ... Any value of `X-User-Role`
    outside this set, or any request that omits one of the required
    headers when they are required, is rejected with `ERR_UNAUTHENTICATED`
    and HTTP 401."

    Design: Corner/rbac/unauthenticated_request_returns_401
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DUN", name="Un", poverty_index_pct=0.00)
    res = api.get_district(district["id"], make_unauthenticated_headers())
    err = validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert err["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value
