"""Entity creation / constraints, RBAC (segregation of duties + ownership), and the
optimistic-concurrency guard on grant staging (PRD 2.1, 2.4, 2.6, 3.1-3.3, 3.8).
"""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_giving_scenario,
    create_program,
    create_active_program,
    create_approved_charity,
    create_employee,
    create_live_campaign,
    create_settled_donation,
    create_open_batch,
    stage_grant,
    make_employee_headers,
    create_charity_payload,
    create_employee_payload,
    create_donation_payload,
    stage_grant_payload,
    build_user_headers,
)

PM = TEST_USERS["program_manager_headers"]
GA = TEST_USERS["giving_admin_headers"]


# ===========================================================================
# Corner / entities
# ===========================================================================
def test_create_program_returns_201_with_defaults(api):
    """PRD 3.1: "the employer matches every donated dollar at a flat `match_ratio`, which defaults
    to 0.5 dollars matched per dollar donated ... Regardless of mode, an employee may receive at
    most `annual_match_cap_cents` (default 100000 cents) in matched dollars per `tax_year`."
    PRD 2.4: "The `version` field is an integer that begins at 1 on creation."

    Design: Corner/entities/create_program_returns_201_with_defaults
    """
    prog = validate_success(api.create_program({"name": "P", "tax_year": 2026}, PM), expected_status=201)
    assert prog["status"] == "DRAFT"
    assert prog["match_ratio"] == 0.5
    assert prog["annual_match_cap_cents"] == 100000
    assert prog["version"] == 1


def test_program_not_found_returns_404(api):
    """PRD 2.9: "the platform validates those identifiers in the order they appear, left to right
    in the path before body references, and rejects the first one that does not resolve to an
    existing resource with `ERR_NOT_FOUND`."

    Design: Corner/entities/program_not_found_returns_404
    """
    resp = api.get_program(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_employee_missing_required_field_rejected(api):
    """PRD 2.10: "fifth, request-body well-formedness — required fields present, enum values
    valid, amounts and minutes strictly greater than zero, EIN in the format of two digits, a
    hyphen, then seven digits (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_employee_missing_required_field_returns_invalid_request
    """
    prog = create_program()
    payload = {"program_id": prog["id"], "email": "e@co.com", "annual_salary_cents": 1000000}
    resp = api.create_employee(payload, GA)  # missing full_name
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_donation_invalid_enum_rejected(api):
    """PRD 2.10: "fifth, request-body well-formedness — required fields present, enum values
    valid, amounts and minutes strictly greater than zero, EIN in the format of two digits, a
    hyphen, then seven digits (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_donation_invalid_enum_returns_invalid_request
    """
    s = setup_giving_scenario()
    payload = create_donation_payload(
        s["program"]["id"], s["employee"]["id"], s["campaign"]["id"],
        donation_type="WEEKLY", base_amount_cents=1000,
    )
    resp = api.create_donation(payload, GA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_charity_bad_eligibility_on_approve_rejected(api):
    """PRD 3.3: "Approval moves it to `APPROVED` but only when the charity is genuinely eligible:
    `claimed_501c3` must be true and the `ein` must match the two-digit, hyphen, seven-digit
    format; if either condition fails, approval is rejected with `ERR_CHARITY_NOT_ELIGIBLE`."

    Design: Corner/entities/charity_bad_ein_format_on_approve_rejected
    """
    prog = create_active_program()
    charity = get_success_data(
        api.create_charity(
            create_charity_payload(prog["id"], legal_name="BadEin", ein="31-3131313", claimed_501c3=False), GA
        )
    )
    api.start_review_charity(charity["id"], GA)
    resp = api.approve_charity(charity["id"], GA)
    validate_error(resp, ApiErrorId.ERR_CHARITY_NOT_ELIGIBLE.value)


def test_employee_system_fields_initialized_on_create(api):
    """PRD 3.2: "On enrollment, an employee starts `ACTIVE` with both consumed-quota counters —
    `match_consumed_ytd_cents` and `dfd_consumed_ytd_cents` — at zero."

    Design: Corner/entities/employee_system_fields_ignored_on_create
    """
    prog = create_program()
    emp = validate_success(
        api.create_employee(create_employee_payload(prog["id"], email="sf@co.com", full_name="Sf"), GA),
        expected_status=201,
    )
    assert emp["match_consumed_ytd_cents"] == 0
    assert emp["dfd_consumed_ytd_cents"] == 0
    assert emp["status"] == "ACTIVE"


def test_duplicate_ein_in_program_rejected(api):
    """PRD 3.3: "The EIN must be unique within the program among charities that are not `REJECTED`;
    a duplicate EIN against a non-rejected charity is rejected with `ERR_DUPLICATE_EIN`."

    Design: Corner/entities/duplicate_ein_in_program_rejected
    """
    prog = create_program()
    api.create_charity(create_charity_payload(prog["id"], legal_name="First", ein="32-3232323"), GA)
    resp = api.create_charity(create_charity_payload(prog["id"], legal_name="Second", ein="32-3232323"), GA)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EIN.value)


def test_duplicate_employee_email_in_program_rejected(api):
    """PRD 3.2: "An email must be unique within its `program_id` among employees who are not
    `TERMINATED`; submitting an email already in use by a non-terminated employee in the same
    program is rejected with `ERR_DUPLICATE_EMPLOYEE_EMAIL`."

    Design: Corner/entities/duplicate_employee_email_in_program_rejected
    """
    prog = create_program()
    api.create_employee(create_employee_payload(prog["id"], email="dup@co.com", full_name="First"), GA)
    resp = api.create_employee(create_employee_payload(prog["id"], email="dup@co.com", full_name="Second"), GA)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_EMAIL.value)


def test_list_employees_paginated_envelope(api):
    """PRD 2.3: "The response envelope's `meta` object on a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_employees_paginated_envelope
    """
    prog = create_program()
    api.create_employee(create_employee_payload(prog["id"], email="l@co.com", full_name="L"), GA)

    resp = api.list_employees(GA, params={"program_id": prog["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ===========================================================================
# Corner / rbac
# ===========================================================================
def test_missing_user_context_header_rejected(api):
    """PRD 2.1: "Every request to the API must be authenticated through two mandatory HTTP
    headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the
    operational capacity in which they are acting. If either header is missing or malformed, the
    request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    resp = api.create_program({"name": "P", "tax_year": 2026}, {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_employee_cannot_approve_charity_segregation(api):
    """PRD 2.1: "When a request's role is not permitted to perform the requested operation, the
    platform responds with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/employee_cannot_approve_charity_segregation
    """
    prog = create_program()
    charity = get_success_data(
        api.create_charity(create_charity_payload(prog["id"], legal_name="C", ein="59-5959595"), GA)
    )
    api.start_review_charity(charity["id"], GA)
    emp = create_employee(prog["id"], email="ec@co.com", full_name="Ec")

    resp = api.approve_charity(charity["id"], make_employee_headers(emp["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_program_manager_cannot_settle_donation_segregation(api):
    """PRD 2.1: "When a request's role is not permitted to perform the requested operation, the
    platform responds with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/program_manager_cannot_settle_donation_segregation
    """
    s = setup_giving_scenario()
    from test_helpers import create_authorized_donation

    don = create_authorized_donation(s, base_amount_cents=5000)
    resp = api.settle_donation(don["id"], PM)  # settle is GivingAdmin-exclusive
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_employee_cannot_cancel_other_employees_donation(api):
    """PRD 2.1: "for the employee-acted operations — cancelling a donation, and pausing, resuming,
    or cancelling a payroll-deduction schedule — the acting employee's `X-User-ID` must equal the
    target resource's `employee_id`; otherwise the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/employee_cannot_cancel_other_employees_donation
    """
    prog = create_active_program()
    charity = create_approved_charity(prog["id"], legal_name="C", ein="61-6161616")
    emp_a = create_employee(prog["id"], email="ea@co.com", full_name="Ea")
    emp_b = create_employee(prog["id"], email="eb@co.com", full_name="Eb")
    camp = create_live_campaign(prog["id"], charity["id"], name="C", goal_cents=100000)

    payload = create_donation_payload(prog["id"], emp_a["id"], camp["id"], base_amount_cents=5000)
    don = get_success_data(api.create_donation(payload, make_employee_headers(emp_a["id"])))

    # Employee B attempts to cancel A's donation.
    resp = api.cancel_donation(don["id"], make_employee_headers(emp_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    after = validate_success(api.get_donation(don["id"], GA))
    assert after["status"] == "PLEDGED"


# ===========================================================================
# Corner / cross_cutting_complexity_layers (OCC)
# ===========================================================================
def test_occ_stale_batch_version_on_grant_stage(api):
    """PRD 2.6: "If `expected_batch_version` does not equal the batch's current `version` —
    meaning another writer has advanced the batch since the client last read it — the staging
    request is rejected with `ERR_STALE_BATCH_VERSION` and HTTP status 412, forcing the client to
    re-read the batch before staging again."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_batch_version_on_grant_stage
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    d1 = create_settled_donation(s, base_amount_cents=5000)
    d2 = create_settled_donation(s, base_amount_cents=6000)

    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])
    v0 = batch["version"]
    # First stage advances the batch version past v0.
    stage_grant(batch["id"], "DONATION", d1["id"], v0)

    # Second stage carries the now-stale v0 -> 412.
    resp = api.stage_grant(batch["id"], stage_grant_payload("DONATION", d2["id"], v0), GA)
    validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION.value)


def test_occ_correct_version_succeeds_and_bumps_version(api):
    """PRD 3.8: "Staging a grant increments the batch's `version` by one (which is what makes the
    OCC guard meaningful)."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps_version
    """
    s = setup_giving_scenario(campaign_overrides={"goal_cents": 1000000})
    d1 = create_settled_donation(s, base_amount_cents=5000)
    batch = create_open_batch(s["program"]["id"], s["charity"]["id"])
    assert batch["version"] == 1

    grant = validate_success(
        api.stage_grant(batch["id"], stage_grant_payload("DONATION", d1["id"], batch["version"]), GA),
        expected_status=201,
    )
    refreshed = validate_success(api.get_disbursement_batch(batch["id"], GA))
    assert refreshed["version"] == 2
