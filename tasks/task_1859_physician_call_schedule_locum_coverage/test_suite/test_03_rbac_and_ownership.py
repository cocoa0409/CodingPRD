"""Role-based access control and entity-backed Physician ownership checks."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_draft_program,
    create_physician,
    create_staff_physician,
    create_window,
    create_window_payload,
    make_physician_headers,
    setup_claimed_swap,
    setup_credentialing_case,
    setup_posted_swap,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CHIEF = TEST_USERS["chief_headers"]


def test_missing_auth_context_header_returns_error(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system
    does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_context_header_returns_error
    """
    headers = {"X-User-ID": "test-no-role", "Content-Type": "application/json"}
    resp = api.list_programs(headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


def test_physician_cannot_publish_program_role_denied_beats_existence(api):
    """PRD §2.11: "When a request would fail several checks at once, the server
    reports the earliest failure in a fixed evaluation order rather than an
    arbitrary one: ... 2. Role permission — a role outside the endpoint's
    authorized list yields `ERR_FORBIDDEN`. ... 5. Existence — ..."

    Design: Corner/validations/physician_cannot_publish_program_role_denied_beats_existence
    """
    physician = create_staff_physician("Dr A")
    resp = api.publish_program(NON_EXISTENT_UUID, make_physician_headers(physician["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_physician_cannot_create_window_for_other_physician(api):
    """PRD §2.1: "a physician may create or cancel only their own unavailability
    windows ... violations are rejected with `ERR_OWNERSHIP_VIOLATION`
    (HTTP 403)."

    Design: Corner/validations/physician_cannot_create_window_for_other_physician
    """
    p1 = create_staff_physician("Dr A")
    p2 = create_staff_physician("Dr B")
    resp = api.create_window(
        create_window_payload(p2["id"], start_date="2026-09-05", end_date="2026-09-06"),
        make_physician_headers(p1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION, 403)


def test_physician_cannot_offer_others_assignment_for_swap(api):
    """PRD §3.4: "The request carries `assignment_id`; the assignment must belong
    to the caller (`ERR_OWNERSHIP_VIOLATION`)".

    Design: Corner/validations/physician_cannot_offer_others_assignment_for_swap
    """
    ctx = setup_posted_swap()
    other = ctx["claimant"]  # a physician who does not own the assignment
    resp = api.create_swap(
        {"assignment_id": ctx["assignment"]["id"]}, make_physician_headers(other["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION, 403)
    swaps, _meta = validate_paginated(
        api.list_swaps(ADMIN, params={"assignment_id": ctx["assignment"]["id"]})
    )
    assert len(swaps) == 1, "the rejected offer must not persist a second swap"


def test_physician_cannot_create_program(api):
    """PRD §2.1: "Every endpoint restricts which roles may invoke it; a caller
    whose role is not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/call-programs is authorized for SchedulerAdmin only.

    Design: Corner/rbac/physician_cannot_create_program
    """
    physician = create_staff_physician("Dr A")
    resp = api.create_program(
        {
            "name": "Nope",
            "service_line": "CARDIOLOGY",
            "period_start": "2026-09-08",
            "period_end": "2026-09-08",
            "payroll_budget_cents": 1_000_000,
        },
        make_physician_headers(physician["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    programs, meta = validate_paginated(api.list_programs(ADMIN))
    assert programs == [], "the forbidden create must not persist a program"


def test_scheduler_admin_cannot_complete_credentialing_item(api):
    """PRD §2.1: "a caller whose role is not on that list is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/credentialing-cases/{id}/complete-item is authorized for
    CredentialingOfficer only.

    Design: Corner/rbac/scheduler_admin_cannot_complete_credentialing_item
    """
    _program, _slot, _gap, _req, _locum, case = setup_credentialing_case()
    resp = api.complete_item(case["id"], "license_verification", ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    after = validate_success(api.get_case(case["id"], TEST_USERS["cred_officer_headers"]))
    assert after["status"] == "INITIATED"
    assert all(v.get("completed_at") is None for v in after["items"].values())


def test_chief_of_staff_cannot_approve_unavailability_window(api):
    """PRD §2.1: "a caller whose role is not on that list is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /api/unavailability-windows/{id}/approve is authorized for
    SchedulerAdmin only.

    Design: Corner/rbac/chief_of_staff_cannot_approve_unavailability_window
    """
    physician = create_staff_physician("Dr A")
    window = create_window(
        physician["id"], start_date="2026-09-05", end_date="2026-09-06"
    )
    resp = api.approve_window(window["id"], CHIEF)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    after = validate_success(api.get_window(window["id"], ADMIN))
    assert after["status"] == "REQUESTED"
