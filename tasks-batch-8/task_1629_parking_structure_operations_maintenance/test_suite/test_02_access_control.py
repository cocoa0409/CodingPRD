"""Access control: context headers, role authorization, identity bindings,
and ownership checks (PRD user/role model and enforcement pipeline)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_access_device_payload,
    create_facility,
    create_facility_payload,
    create_parker,
    create_rate_schedule_payload,
    create_shift_payload,
    get_success_data,
    issue_credential,
    make_gate_device_headers,
    make_monthly_parker_headers,
    open_shift,
    register_online_gate,
    setup_entry_ready_facility,
    submit_agreement,
    create_repair_project,
    validate_error,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]
AUD = TEST_USERS["revenue_auditor_headers"]
SEC = TEST_USERS["security_officer_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD: "A request missing either header, or carrying a role outside this
    list, is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    res = api.list_facilities(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_CONTEXT_HEADER)


def test_role_forbidden_for_endpoint(api):
    """PRD: "Once identified, the caller's role must appear in the endpoint's
    authorized role list; a caller whose role is not listed is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD endpoint table: "| POST | `/ops/facilities` | Create a facility |
    FacilityManager |"

    Design: Corner/validations/role_forbidden_for_endpoint
    """
    res = api.create_facility(
        create_facility_payload(name="Nope", total_spaces=10, monthly_capacity=1,
                                event_pool_spaces=1),
        make_monthly_parker_headers("11111111-1111-1111-1111-111111111111"))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_attendant_cannot_reconcile(api):
    """PRD endpoint table: "| POST | `/ops/reconciliations` | Open a
    reconciliation for a CLOSED/FORCE_CLOSED shift | RevenueAuditor |"
    PRD: "Once identified, the caller's role must appear in the endpoint's
    authorized role list; a caller whose role is not listed is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD: "Incoming requests are checked in a fixed pipeline order, and when
    several checks could fail, the earliest failure is the one reported."

    Design: Corner/rbac/attendant_cannot_reconcile
    """
    res = api.create_reconciliation({"shift_id": NON_EXISTENT_UUID}, ATT)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_auditor_cannot_close_shift(api):
    """PRD endpoint table: "| POST | `/ops/shifts/{shift_id}/close` | Close a
    shift with the declared cash count | ParkingAttendant |"
    PRD: "a caller whose role is not listed is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/auditor_cannot_close_shift
    """
    facility = create_facility(name="RB2 Fac")
    shift = open_shift(facility["id"])
    res = api.close_shift(shift["id"], {"counted_cash_cents": 10000}, AUD)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = get_success_data(api.get_shift(shift["id"], FM))
    assert after["shift_status"] == "OPEN"


def test_gate_device_cannot_manage_rates(api):
    """PRD endpoint table: "| POST | `/ops/rate-schedules` | Create a DRAFT rate
    schedule | FacilityManager |"
    PRD: "a caller whose role is not listed is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/gate_device_cannot_manage_rates
    """
    facility = create_facility(name="RB3 Fac")
    device = get_success_data(api.create_access_device(
        create_access_device_payload(facility["id"], device_label="E1"), FM))
    res = api.create_rate_schedule(
        create_rate_schedule_payload(facility["id"], label="Hacked"),
        make_gate_device_headers(device["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_security_officer_cannot_fund_projects(api):
    """PRD endpoint table: "| POST | `/ops/repair-projects/{repair_project_id}/fund`
    | Draw capital reserve to fund the project | FacilityManager |"
    PRD: "a caller whose role is not listed is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/security_officer_cannot_fund_projects
    """
    facility = create_facility(name="RB4 Fac")
    project = create_repair_project(facility["id"], title="Sealant",
                                    estimated_cost_cents=1000)
    res = api.fund_repair_project(project["id"], 1000, SEC)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    after = get_success_data(api.get_repair_project(project["id"], FM))
    assert after["project_status"] == "PROPOSED"


def test_device_identity_mismatch_on_entry(api):
    """PRD: "When `X-User-Role` is `GateDevice`, `X-User-ID` is the `id` of the
    acting AccessDevice; ownership checks compare it against the device being
    acted upon — the device identifier in the path for heartbeat and fault
    reporting, and the `entry_device_id` supplied in the body when recording a
    gate entry — and a mismatch is rejected with
    `ERR_DEVICE_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/validations/device_identity_mismatch_on_entry
    """
    facility, schedule, gate_a = setup_entry_ready_facility(name="IM Fac")
    gate_b = register_online_gate(facility["id"], device_label="GB")
    res = api.create_parking_session(
        {"facility_id": facility["id"], "entry_device_id": gate_b["id"],
         "ticket_barcode": "IM-1"},
        make_gate_device_headers(gate_a["id"]))
    validate_error(res, ApiErrorId.ERR_DEVICE_IDENTITY_MISMATCH)


def test_parker_not_owner_cannot_report_lost(api):
    """PRD: "When `X-User-Role` is `MonthlyParker`, `X-User-ID` is the `id` of
    the acting ParkerAccount; ownership checks on any resource that references
    a parker compare that resource's parker-account foreign key against
    `X-User-ID`, so a parker attempting to report another parker's credential
    lost or withdraw another parker's waitlisted agreement is rejected with
    `ERR_NOT_OWNER` (HTTP 403)."

    Design: Corner/validations/parker_not_owner_cannot_report_lost
    """
    facility = create_facility(name="NO Fac")
    owner = create_parker(full_name="NO One", email="no1@x.com")
    agreement = submit_agreement(facility["id"], owner["id"])
    credential = issue_credential(agreement["id"], "BADGE", 5000)
    other = create_parker(full_name="NO Two", email="no2@x.com")

    res = api.report_credential_lost(credential["id"],
                                     make_monthly_parker_headers(other["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_OWNER)
    after = get_success_data(api.get_credential(credential["id"], FM))
    assert after["credential_status"] == "ACTIVE"
