"""Authentication, role-based authorization, and paginated listing.

Covers corner queue B:
  rbac:
    - missing_auth_header_rejected
    - advisor_cannot_create_program
    - registrar_cannot_release_disbursement
  endpoints:
    - list_attendance_entries_paginated_filtered_by_agreement
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
FAID = TEST_USERS["financial_aid_officer_headers"]
ADVISOR = TEST_USERS["academic_advisor_headers"]


# --------------------------------------------------------------------------
# rbac: missing_auth_header_rejected
# --------------------------------------------------------------------------
def test_missing_auth_header_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: X-User-ID, which identifies the acting user, and X-User-Role, which
    declares the operational capacity under which the request is made. If either
    header is missing or malformed, the request is rejected with
    ERR_MISSING_AUTH_HEADER."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    resp = api.list_programs(headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER.value)


# --------------------------------------------------------------------------
# rbac: advisor_cannot_create_program
# --------------------------------------------------------------------------
def test_advisor_cannot_create_program(api):
    """PRD §2.1: "If the headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."
    PRD §2.1: "SystemAdmin owns program configuration and the deterministic term
    clock."

    Design: Corner/rbac/advisor_cannot_create_program
    """
    resp = api.create_program(
        {"name": "P", "credential_type": "DIPLOMA", "required_clock_hours": 1000,
         "required_theory_hours": 600, "required_externship_hours": 400, "tuition_cents": 0},
        ADVISOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# --------------------------------------------------------------------------
# rbac: registrar_cannot_release_disbursement
# --------------------------------------------------------------------------
def test_registrar_cannot_release_disbursement(api):
    """PRD §2.1: "If the headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED."
    PRD §2.1: "FinancialAidOfficer owns aid disbursement and refund computation
    and settlement."

    Design: Corner/rbac/registrar_cannot_release_disbursement
    """
    program, cohort, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 1_000_000},
        agreement_overrides={"contract_tuition_cents": 1_000_000, "scheduled_aid_cents": 800_000},
    )
    draw = fx.schedule_disbursement(agreement["id"], disbursement_index=1,
                                    planned_amount_cents=200_000, required_clock_hours_gate=0)
    resp = api.release_disbursement(draw["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# --------------------------------------------------------------------------
# endpoints: list_attendance_entries_paginated_filtered_by_agreement
# --------------------------------------------------------------------------
def test_list_attendance_entries_paginated_filtered_by_agreement(api):
    """PRD §2.3: "List responses include the following fields in the meta object
    of the response envelope: limit, offset, total_count, and has_more."
    PRD §4: "GET | /v1/attendance-entries | List attendance entries (filters:
    agreement_id, status, kind)"

    Design: Corner/endpoints/list_attendance_entries_paginated_filtered_by_agreement
    """
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"required_clock_hours": 1000, "tuition_cents": 0},
        agreement_overrides={"contract_tuition_cents": 0},
    )
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=10, attended_hours=10, term_index=1)
    fx.post_attendance(agreement["id"], kind="THEORY", scheduled_hours=10, attended_hours=10, term_index=2)
    resp = api.list_attendance_entries(
        ADVISOR, params={"agreement_id": agreement["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data
