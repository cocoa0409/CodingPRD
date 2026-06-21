"""Access-control and concurrency tests: authentication, authorization, segregation of duties,
and optimistic concurrency (stale worker version, correct batch version).

Queue B (Corner): rbac.* and cross_cutting_complexity_layers OCC instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    build_user_headers,
    ApiErrorId,
    TEST_USERS,
    make_payroll_officer_headers,
    make_compliance_officer_headers,
    create_employer,
    create_standard_policy,
    create_fee_schedule,
    create_pay_period,
    create_worker,
    post_time_entry,
    post_shift_10h_gross_20000,
    setup_base_scenario,
    request_advance,
    lock_period,
    open_batch,
    run_payday,
    get_worker_version,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["payroll_officer_headers"]
POSTER = TEST_USERS["payroll_poster_headers"]
SIGNER = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Queue B — rbac / missing_headers_returns_unauthenticated
# ===========================================================================
def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` value that is not
    a recognized role, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api._request("GET", "/employers", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Queue B — rbac / worker_cannot_create_employer_returns_unauthorized
# ===========================================================================
def test_worker_cannot_create_employer_returns_unauthorized(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: POST `/employers` is authorized for `PlatformAdmin` only.

    Design: Corner/rbac/worker_cannot_create_employer_returns_unauthorized
    """
    worker_headers = build_user_headers("some-worker-id", "Worker")
    resp = api.create_employer({"legal_name": "Acme", "state_code": "CA", "pay_frequency": "WEEKLY"},
                               worker_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# Queue B — rbac / payroll_officer_cannot_write_off_returns_unauthorized
# ===========================================================================
def test_payroll_officer_cannot_write_off_returns_unauthorized(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.11: "Authorization is checked next: a role not permitted for the operation yields
    `ERR_UNAUTHORIZED`."
    PRD §4: POST `/advances/{advanceId}/write-off` is authorized for `ComplianceOfficer` only.

    Authorization precedes state, so a PayrollOfficer write-off is rejected regardless of advance
    state.

    Design: Corner/rbac/payroll_officer_cannot_write_off_returns_unauthorized
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    adv = request_advance(worker["id"], period["id"], 5000)

    resp = api.write_off_advance(adv["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# Queue B — rbac / segregation_of_duties_signer_cannot_be_poster
# ===========================================================================
def test_segregation_of_duties_signer_cannot_be_poster(api):
    """PRD §2.8: "when a statement is signed, the acting user must not be the poster of the
    period's batch and must not be the approver of any advance in the period. ... A violation at
    either point is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    A period with no advances yields a CLEAN statement (drift 0). Posting the batch as
    'dual-user' (PayrollOfficer) then signing as the SAME 'dual-user' (ComplianceOfficer) violates
    SoD => ERR_SEGREGATION_OF_DUTIES.

    Design: Corner/rbac/segregation_of_duties_signer_cannot_be_poster
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    lock_period(period["id"])
    batch = open_batch(period["id"])
    b_v = validate_success(api.get_repayment_batch(batch["id"], OFFICER))["version"]
    get_success_data(api.post_repayment_batch(
        batch["id"], {"expected_repaymentbatch_version": b_v},
        make_payroll_officer_headers("dual-user")))
    run_payday(period["id"])
    stmt = validate_success(api.create_reconciliation_statement({"pay_period_id": period["id"]}, SIGNER))
    assert stmt["outcome"] == "CLEAN", f"no advances => CLEAN; got {stmt['outcome']}"

    resp = api.sign_reconciliation_statement(stmt["id"], make_compliance_officer_headers("dual-user"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ===========================================================================
# Queue B — rbac / clean_statement_sign_by_distinct_compliance_user_succeeds
# ===========================================================================
def test_clean_statement_sign_by_distinct_compliance_user_succeeds(api):
    """PRD §3.11: "Signing a statement is a `ComplianceOfficer` action that moves it `DRAFT →
    SIGNED`. ... On success the statement records `signed_by_user_id` as the acting `X-User-ID`".

    A period with no advances => CLEAN statement; posted by 'officer-poster' and signed by the
    distinct ComplianceOfficer 'compliance-signer' succeeds (DRAFT -> SIGNED), recording the signer.

    Design: Corner/rbac/clean_statement_sign_by_distinct_compliance_user_succeeds
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    lock_period(period["id"])
    batch = open_batch(period["id"])
    b_v = validate_success(api.get_repayment_batch(batch["id"], OFFICER))["version"]
    get_success_data(api.post_repayment_batch(
        batch["id"], {"expected_repaymentbatch_version": b_v},
        make_payroll_officer_headers("officer-poster")))
    run_payday(period["id"])
    stmt = validate_success(api.create_reconciliation_statement({"pay_period_id": period["id"]}, SIGNER))

    signed = validate_success(api.sign_reconciliation_statement(
        stmt["id"], make_compliance_officer_headers("compliance-signer")))
    assert signed["status"] == "SIGNED", f"distinct signer must succeed; got {signed['status']}"
    assert signed["signed_by_user_id"] == "compliance-signer", (
        f"signed_by_user_id must record the signer; got {signed['signed_by_user_id']}"
    )


# ===========================================================================
# Queue B — cross_cutting / occ_stale_worker_version_on_second_advance
# ===========================================================================
def test_occ_stale_worker_version_on_second_advance(api):
    """PRD §2.7: "When a `Worker` (or a `PayrollOfficer` acting on a worker's behalf) requests a
    new advance, the create request must include `expected_worker_version` carrying the client's
    last observed `version` of the target `Worker`. If that value does not equal the worker's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "increments the target worker's `version` by one."

    The first create bumps the worker version; a second create still carrying the pre-bump version
    is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_worker_version_on_second_advance
    """
    employer, _p, _f, period, worker = setup_base_scenario()
    post_shift_10h_gross_20000(period["id"], worker["id"])
    w_v = get_worker_version(worker["id"])
    get_success_data(api.create_advance(
        {"worker_id": worker["id"], "pay_period_id": period["id"], "requested_principal_cents": 3000,
         "disbursement_speed": "STANDARD", "tip_cents": 0, "expected_worker_version": w_v}, OFFICER))

    resp = api.create_advance(
        {"worker_id": worker["id"], "pay_period_id": period["id"], "requested_principal_cents": 2000,
         "disbursement_speed": "STANDARD", "tip_cents": 0, "expected_worker_version": w_v}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ===========================================================================
# Queue B — cross_cutting / occ_correct_batch_version_post_succeeds
# ===========================================================================
def test_occ_correct_batch_version_post_succeeds(api):
    """PRD §2.7: "When a `PayrollOfficer` posts a repayment batch, the post request must include
    `expected_repaymentbatch_version` carrying the client's last observed `version` of the target
    `RepaymentBatch`."
    PRD §3.8: "the post must carry `expected_repaymentbatch_version` matching the batch's current
    `version`, else `ERR_STALE_VERSION`. On success it ... increments the batch's `version` by one."

    Posting with the current batch version succeeds (DRAFT -> POSTED) and bumps the version.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_batch_version_post_succeeds
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    lock_period(period["id"])
    batch = open_batch(period["id"])
    b_v = validate_success(api.get_repayment_batch(batch["id"], OFFICER))["version"]

    posted = validate_success(api.post_repayment_batch(
        batch["id"], {"expected_repaymentbatch_version": b_v}, POSTER))
    assert posted["status"] == "POSTED", f"correct version must post; got {posted['status']}"
    assert posted["version"] > b_v, f"batch version must increment over {b_v}; got {posted['version']}"
