"""Authentication, authorization priority, and segregation-of-duties rules
(PRD §2.1, §2.10, §3.1, §3.5, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    create_program_payload, create_funder_payload, create_funding_pool_payload,
    create_retailer_payload, create_redemption_payload,
    TEST_USERS, make_funder_analyst_headers, make_clinic_staff_headers,
    make_participant_headers, make_retailer_staff_headers,
    create_clinic, create_funder, create_program, create_pool,
    create_patient, setup_settled_redemption, setup_submitted_report,
    get_pool,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role string
    that is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.10: "First, authentication: the `X-User-Role` and `X-User-ID`
    headers must be present and the role must be a declared role, otherwise
    `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/c_missing_header_returns_unauthenticated
    """
    res = api.get_program(NON_EXISTENT_UUID, None)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_wrong_role_create_program_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted on the target endpoint,
    or whose entity-backed ownership check fails, is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /programs is authorized for ProgramAdmin only.

    Design: Corner/validations/c_wrong_role_create_program_forbidden
    """
    clinic = create_clinic()
    res = api.create_program(
        create_program_payload(), make_clinic_staff_headers(clinic["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_clinic_scope_mismatch_forbidden(api):
    """PRD §3.2: "Clinic staff register patients at their own clinic: the
    payload's `clinic_id` must equal the acting `X-User-ID`, and a mismatch is
    `ERR_FORBIDDEN`."

    Design: Corner/validations/c_clinic_scope_mismatch_forbidden
    """
    clinic_a = create_clinic(name="CA")
    clinic_b = create_clinic(name="CB")
    res = api.create_patient(
        {"clinic_id": clinic_b["id"], "full_name": "Pat X",
         "date_of_birth": "1990-01-01", "household_size": 1},
        make_clinic_staff_headers(clinic_a["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_authorization_precedes_not_found(api):
    """PRD §2.10: "Second, authorization: the role must be allowed on the
    endpoint and entity-backed ownership must hold — a `ClinicStaff` caller's
    clinic must match the resource's clinic, a `RetailerStaff` caller's
    retailer must match, a `FunderAnalyst` caller's funder scope must hold,
    and a `Participant` reads only their own records — otherwise
    `ERR_FORBIDDEN`. Third, existence: every referenced id must resolve — path
    parameters first, validated left to right, then body foreign keys in
    payload order — otherwise `ERR_NOT_FOUND`."

    Design: Corner/validations/c_authz_precedes_not_found
    """
    clinic = create_clinic()
    res = api.activate_program(
        NON_EXISTENT_UUID, make_clinic_staff_headers(clinic["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_funder_cannot_fund_other_funders_pool(api):
    """PRD §3.1: "Only the pool's own funder may fund it — a `FunderAnalyst`
    whose `X-User-ID` equals the pool's `funder_id`, otherwise `ERR_FORBIDDEN`
    — and funding additionally requires the funder itself to be ACTIVE
    (otherwise `ERR_INVALID_STATE`) and the program to be in DRAFT, ACTIVE, or
    FROZEN (otherwise `ERR_PROGRAM_NOT_ACTIVE`)."

    Design: Corner/rbac/c_funder_cannot_fund_other_pool
    """
    funder_a = create_funder(name="FA")
    funder_b = create_funder(name="FB")
    program = create_program()
    pool = create_pool(program["id"], funder_a["id"], committed_cents=500000)

    res = api.fund_pool(pool["id"], make_funder_analyst_headers(funder_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")

    pool_after = get_pool(pool["id"])
    assert pool_after["status"] == "PENDING"


def test_retailer_cannot_void_other_retailers_redemption(api):
    """PRD §3.5: "Voiding unwinds all of it, and is available to the cashier's
    own retailer or to a `ProgramAdmin`, with a mandatory `reason`."
    PRD §2.1: "a retail cashier sees only their own retailer's redemptions."

    Design: Corner/rbac/c_retailer_cannot_void_others_redemption
    """
    ctx = setup_settled_redemption(
        lines=[{"category": "STAPLE", "amount_cents": 1000}])
    redemption = ctx["redemption"]
    retailer_b = validate_success(api.create_retailer(
        create_retailer_payload(name="RB", kind="FARMERS_MARKET",
                                double_up_eligible=True), ADMIN), 201)

    res = api.void_redemption(
        redemption["id"], {"reason": "not mine"},
        make_retailer_staff_headers(retailer_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")

    after = validate_success(api.get_redemption(redemption["id"], ADMIN), 200)
    assert after["status"] == "SETTLED"


def test_admin_cannot_accept_report_forbidden(api):
    """PRD §3.9: "Reporting follows a strict segregation of duties: the
    `ProgramAdmin` compiles and submits reports, and only the funder whose
    money is being reported on may adjudicate them."

    Design: Corner/rbac/c_admin_cannot_accept_report_forbidden
    """
    ctx = setup_submitted_report()
    report = ctx["report"]

    res = api.accept_report(report["id"], ADMIN)
    validate_error(res, "ERR_FORBIDDEN")

    after = validate_success(api.get_funder_report(report["id"], ADMIN), 200)
    assert after["status"] == "SUBMITTED"


def test_participant_reads_own_record_and_not_others(api):
    """PRD §2.1: "a participant reads only their own records — their own
    patient profile, their own enrollments, and their own vouchers — and any
    attempt to reach another patient's record is `ERR_FORBIDDEN`."

    Design: Corner/rbac/c_participant_reads_own_record_and_not_others
    """
    clinic = create_clinic()
    patient_a = create_patient(clinic["id"], full_name="Pat A", household_size=2)
    patient_b = create_patient(clinic["id"], full_name="Pat B", household_size=3)

    own = validate_success(
        api.get_patient(patient_a["id"], make_participant_headers(patient_a["id"])),
        200)
    assert own["full_name"] == "Pat A"

    res = api.get_patient(patient_b["id"], make_participant_headers(patient_a["id"]))
    validate_error(res, "ERR_FORBIDDEN")
