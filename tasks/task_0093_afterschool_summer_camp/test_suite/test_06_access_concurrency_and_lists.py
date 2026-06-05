"""Role-based access control, optimistic concurrency, and list/pagination reads.

Covers corner rbac instances (forbidden role, peer isolation, unauthenticated), the
corner cross-cutting OCC instances (stale offering / invoice version), and the corner
endpoint + pagination instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_program_payload,
    create_session_payload,
    create_child_payload,
    create_enrollment_payload,
    finalize_invoice_payload,
    make_guardian_headers,
    # fixtures
    create_guardian,
    create_child,
    setup_eligible_child,
    setup_open_session_with_offering,
    setup_confirmed_enrollment,
    get_offering,
    get_invoice,
    enroll_child,
)

DIRECTOR = TEST_USERS["program_director_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# RBAC (corner)
# ---------------------------------------------------------------------------
def test_guardian_cannot_open_session(api):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted to perform
    the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4: "POST /sessions/{id}/open ... Open a scheduled session for enrollment ...
    ProgramDirector" (a Guardian is not authorized).

    Design: Corner/rbac/guardian_cannot_open_session
    """
    guardian = create_guardian()
    program = api_client.create_program(create_program_payload(name="Rb Camp"), DIRECTOR).json()["data"]
    session = api_client.create_session(create_session_payload(program["id"], title="Rb"), DIRECTOR).json()["data"]
    api_client.create_weekly_offering({"session_id": session["id"], "week_start": "2026-06-08"}, DIRECTOR)
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    resp = api.open_session(session["id"], make_guardian_headers(guardian["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_program_director_cannot_finalize_invoice(api):
    """PRD §2.1: "When a caller is authenticated but their role is not permitted to perform
    the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD §4: "POST /invoices/{id}/finalize ... BillingAdmin" (a ProgramDirector is not
    authorized to finalize).

    Design: Corner/rbac/program_director_cannot_finalize_invoice
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Pf Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 15000},
    )
    inv = get_invoice(scene["invoice_id"])
    resp = api.finalize_invoice(scene["invoice_id"], finalize_invoice_payload(inv["version"]), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request to a protected endpoint that is missing either header, or that
    carries a malformed value, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    guardian = create_guardian()
    # POST /children with no auth headers at all.
    resp = api.create_child(create_child_payload(guardian["id"], first_name="Ua"), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Optimistic concurrency control (corner cross-cutting)
# ---------------------------------------------------------------------------
def test_enroll_with_stale_offering_version_rejected(api):
    """PRD §2.9: "Creating an enrollment requires an expected_weekly_offering_version field
    carrying the client's last observed version of the target WeeklyOffering. If the
    offering's current version no longer matches that value ... the create is rejected with
    ERR_STALE_OFFERING_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_offering_version_on_enroll
    """
    scene = setup_open_session_with_offering(
        program_overrides={"name": "Occ Camp", "program_type": "CAMP"},
        session_overrides={"weekly_capacity": 5},
    )
    offering_id = scene["offering"]["id"]
    stale_version = get_offering(offering_id)["version"]
    guardian = create_guardian()
    gid = guardian["id"]
    gh = make_guardian_headers(gid)
    child_a = setup_eligible_child(guardian_id=gid, child_overrides={"first_name": "O1", "birth_date": "2016-01-01"})["child"]
    child_b = setup_eligible_child(guardian_id=gid, child_overrides={"first_name": "O2", "birth_date": "2016-02-01"})["child"]
    # First enroll advances the offering version.
    enroll_child(gid, child_a["id"], offering_id, stale_version)
    # Second enroll reuses the now-stale version.
    resp = api.create_enrollment(create_enrollment_payload(child_b["id"], offering_id, stale_version), gh)
    validate_error(resp, ApiErrorId.ERR_STALE_OFFERING_VERSION.value)


def test_finalize_with_stale_invoice_version_rejected(api):
    """PRD §2.9: "Finalizing an invoice requires an expected_invoice_version field carrying
    the client's last observed version of the target Invoice. A scholarship approval or a
    sibling withdrawal can re-run the invoice totals and bump the invoice's version between
    the moment the administrator reads it and the moment they finalize; if the supplied
    expected_invoice_version no longer matches the invoice's current version, the finalize
    is rejected with ERR_STALE_INVOICE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_invoice_version_on_finalize
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Oin Camp", "program_type": "CAMP"},
        session_overrides={"base_weekly_tuition_cents": 20000},
        with_scholarship_tier="PARTIAL",
        approve_scholarship=False,
    )
    invoice_id = scene["invoice_id"]
    stale_invoice_version = get_invoice(invoice_id)["version"]
    # Approve the scholarship -> re-prices the invoice and bumps its version.
    validate_success(api.approve_scholarship_award(scene["scholarship"]["id"], DIRECTOR), 200)
    resp = api.finalize_invoice(invoice_id, finalize_invoice_payload(stale_invoice_version), BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_INVOICE_VERSION.value)


# ---------------------------------------------------------------------------
# List / pagination reads (corner)
# ---------------------------------------------------------------------------
def test_list_guardian_children_returns_array(api):
    """PRD §4: "GET /guardians/{id}/children | List a guardian's children".
    PRD §2.3: "List responses include these four fields in the meta object: limit, offset,
    total_count, and has_more."

    Design: Corner/endpoints/list_children_of_guardian_paginated
    """
    guardian = create_guardian()
    gid = guardian["id"]
    create_child(gid, first_name="L1", birth_date="2016-01-01")
    create_child(gid, first_name="L2", birth_date="2016-02-01")
    resp = api.list_guardian_children(gid, make_guardian_headers(gid))
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 children, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"


def test_list_enrollments_filtered_by_child(api):
    """PRD §4: "GET /enrollments | List enrollments, filterable by child or invoice".

    Design: Corner/endpoints/filtered_enrollment_list_by_child
    """
    scene = setup_confirmed_enrollment(
        program_overrides={"name": "Fe Camp", "program_type": "AFTERSCHOOL"},
        session_overrides={"base_weekly_tuition_cents": 15000},
    )
    gid = scene["guardian"]["id"]
    resp = api.list_enrollments(make_guardian_headers(gid), params={"child_id": scene["child"]["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 enrollment for the child, got {len(data)}"


def test_audit_entries_pagination_limit_and_has_more(api):
    """PRD §2.3: "The limit parameter sets the maximum number of items returned".
    PRD §4: "GET /audit-entries | List audit entries, filterable by entity".
    PRD §3.1: "Publishing records a PROGRAM_PUBLISHED audit action". PRD §3.2: "Opening
    records a SESSION_OPENED audit action". (Two PRD-named state transitions append two
    audit entries, so >1 exists; with limit=1 the page returns 1 and has_more is true.)

    Design: Corner/cross_cutting_complexity_layers/pagination_limit_offset_on_audit_entries
    """
    program = api_client.create_program(create_program_payload(name="Pg Camp"), DIRECTOR).json()["data"]
    session = api_client.create_session(create_session_payload(program["id"], title="Pg"), DIRECTOR).json()["data"]
    api_client.create_weekly_offering({"session_id": session["id"], "week_start": "2026-06-08"}, DIRECTOR)
    # Two PRD-named transitions -> two audit entries (PROGRAM_PUBLISHED, SESSION_OPENED).
    validate_success(api_client.publish_program(program["id"], DIRECTOR), 200)
    validate_success(api_client.open_session(session["id"], DIRECTOR), 200)
    resp = api.list_audit_entries(DIRECTOR, params={"limit": 1})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return exactly 1 entry, got {len(data)}"
    assert meta["has_more"] is True, f"with >1 audit entry, has_more must be true, got {meta['has_more']}"
