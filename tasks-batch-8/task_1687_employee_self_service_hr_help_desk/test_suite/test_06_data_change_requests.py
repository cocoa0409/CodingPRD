"""Data change requests and fraud verification (PRD §3.7, §2.9, §2.10, §2.11):
parallel approval/fraud dimensions, lockout, approval gates, segregation of
duties, sibling cancellation, and the audit trail."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    make_employee_headers,
    make_steward_headers,
    make_employee,
    set_employee_status,
    employee_version,
    create_dcr,
    get_dcr,
    fraud_verification_of,
    challenge_code_of,
    verify_dcr,
    approve_dcr,
    audit_log_of_employee,
    ADDRESS_NEW_VALUES,
    DIRECT_DEPOSIT_NEW_VALUES,
)

ADMIN = TEST_USERS["admin_headers"]
STEWARD = TEST_USERS["steward_headers"]
STEWARD2 = TEST_USERS["steward2_headers"]


# ---------------------------------------------------------------------------
# Fraud verification retry cycle (parallel dimensions)
# ---------------------------------------------------------------------------

def _deposit_dcr_pending_verification(api, employee_number="E500",
                                      full_name="Dee Deposit", email="dee@x.com"):
    """Employee + DIRECT_DEPOSIT DCR (fraud verification always required)."""
    employee = make_employee(employee_number=employee_number, full_name=full_name, email=email)
    dcr = create_dcr(employee["id"], "DIRECT_DEPOSIT")
    assert dcr["approval_status"] == "PENDING_VERIFICATION"
    assert dcr["fraud_status"] == "PENDING"
    return employee, dcr


def test_failed_verify_moves_only_fraud_dimension(api):
    """PRD §3.7: "A wrong code rejects the attempt with
    `ERR_FRAUD_EVIDENCE_MISMATCH` and records it: `attempts` increments and the
    verification's `status` becomes `FAILED`, with the request's `fraud_status`
    following along."
    PRD §3.7: "Whether fraud verification is required is decided at creation. A
    direct-deposit change always requires it."

    Design: Difficulty/non_linear_state_machine/dcr_parallel_dimensions_fraud_retry_cycle
    """
    employee, dcr = _deposit_dcr_pending_verification(api)

    resp = verify_dcr(dcr["id"], "SECURITY_CODE", employee["id"], evidence_code="BAD000")
    validate_error(resp, ApiErrorId.ERR_FRAUD_EVIDENCE_MISMATCH.value)

    after = get_dcr(dcr["id"])
    assert after["approval_status"] == "PENDING_VERIFICATION", (
        "a failed attempt must not move the approval dimension"
    )
    assert after["fraud_status"] == "FAILED"

    fv = fraud_verification_of(dcr["id"], employee["id"])
    assert fv["attempts"] == 1
    assert fv["status"] == "FAILED"


def test_fraud_retry_then_approve_applies_deposit(api):
    """PRD §3.7: "A successful verification — from `PENDING` or `FAILED`, never from
    `LOCKED` — sets the verification's `status` to `VERIFIED`, records
    `verified_by_user_id` (the employee for the code path, the manager for the
    confirmation path) and `verified_at`, and moves the request's `approval_status`
    from `PENDING_VERIFICATION` to `PENDING_APPROVAL` with `fraud_status` at
    `VERIFIED`."
    PRD §3.7: "An approved request applies atomically. The `new_values` are written
    onto the employee's address or bank block, the employee's `version` increments
    and `updated_at` refreshes, and the server appends one audit log entry per
    changed employee field — each naming the `field_changed`, the string-serialized
    `old_value` (null when the field was previously unset), the `new_value`, the
    approving steward as `changed_by_user_id`, the originating request as `dcr_id`,
    and a `change_source` of `DCR_APPLIED`, the only origin this version of the
    system writes."

    Design: Difficulty/non_linear_state_machine/dcr_parallel_dimensions_fraud_retry_cycle
    """
    employee, dcr = _deposit_dcr_pending_verification(api)
    challenge = challenge_code_of(dcr["id"], employee["id"])

    # One failed attempt, then the correct code.
    validate_error(
        verify_dcr(dcr["id"], "SECURITY_CODE", employee["id"], evidence_code="BAD000"),
        ApiErrorId.ERR_FRAUD_EVIDENCE_MISMATCH.value,
    )
    verified = validate_success(
        verify_dcr(dcr["id"], "SECURITY_CODE", employee["id"], evidence_code=challenge)
    )
    assert verified["approval_status"] == "PENDING_APPROVAL"
    assert verified["fraud_status"] == "VERIFIED"

    applied = approve_dcr(dcr["id"])
    assert applied["approval_status"] == "APPLIED"

    profile = validate_success(api.get_employee(employee["id"], ADMIN))
    assert profile["bank_routing_number"] == DIRECT_DEPOSIT_NEW_VALUES["bank_routing_number"]
    assert profile["bank_account_number"] == DIRECT_DEPOSIT_NEW_VALUES["bank_account_number"]
    assert profile["bank_account_type"] == "CHECKING"

    entries, meta = audit_log_of_employee(employee["id"])
    assert meta["total_count"] == 3, f"one audit entry per changed bank field, got {meta['total_count']}"
    fields = {e["field_changed"] for e in entries}
    assert fields == {"bank_routing_number", "bank_account_number", "bank_account_type"}
    for entry in entries:
        assert entry["change_source"] == "DCR_APPLIED"
        assert entry["dcr_id"] == dcr["id"]


# ---------------------------------------------------------------------------
# Apply cascade: sibling DCRs and the audit trail
# ---------------------------------------------------------------------------

def _employee_with_pending_address_and_deposit(api):
    employee = make_employee(employee_number="E700", full_name="Sid Sibling", email="sid@x.com")
    d1 = create_dcr(employee["id"], "ADDRESS")  # no fraud history -> PENDING_APPROVAL
    assert d1["approval_status"] == "PENDING_APPROVAL"
    d2 = create_dcr(employee["id"], "DIRECT_DEPOSIT",
                    new_values={"bank_routing_number": "021000021",
                                "bank_account_number": "123456789",
                                "bank_account_type": "SAVINGS"})
    assert d2["approval_status"] == "PENDING_VERIFICATION"
    return employee, d1, d2


def test_dcr_apply_writes_profile_and_audit_entries(api):
    """PRD §3.7: "An approved request applies atomically. The `new_values` are
    written onto the employee's address or bank block, the employee's `version`
    increments and `updated_at` refreshes, and the server appends one audit log entry
    per changed employee field — each naming the `field_changed`, the
    string-serialized `old_value` (null when the field was previously unset), the
    `new_value`, the approving steward as `changed_by_user_id`, the originating
    request as `dcr_id`, and a `change_source` of `DCR_APPLIED`, the only origin
    this version of the system writes."

    Design: Difficulty/transitive_cascade/dcr_apply_employee_mutation_cancels_sibling_dcr
    """
    employee, d1, _d2 = _employee_with_pending_address_and_deposit(api)

    applied = approve_dcr(d1["id"])
    assert applied["approval_status"] == "APPLIED"

    profile = validate_success(api.get_employee(employee["id"], ADMIN))
    assert profile["address_line1"] == ADDRESS_NEW_VALUES["address_line1"]
    assert profile["city"] == ADDRESS_NEW_VALUES["city"]
    assert profile["region"] == ADDRESS_NEW_VALUES["region"]
    assert profile["postal_code"] == ADDRESS_NEW_VALUES["postal_code"]

    entries, meta = audit_log_of_employee(employee["id"])
    assert meta["total_count"] == 4, f"one audit entry per address field, got {meta['total_count']}"
    fields = {e["field_changed"] for e in entries}
    assert fields == {"address_line1", "city", "region", "postal_code"}
    for entry in entries:
        assert entry["change_source"] == "DCR_APPLIED"
        assert entry["dcr_id"] == d1["id"]


def test_dcr_apply_cancels_pending_sibling(api):
    """PRD §3.7: "Applying one request invalidates its siblings: every other data
    change request of the same employee still in `PENDING_VERIFICATION` or
    `PENDING_APPROVAL` moves to `CANCELLED`, because a profile mutation invalidates
    any verification already in flight."
    PRD §3.7: "The request records `decided_by_user_id`, `decided_at`, and
    `applied_at`; the employee's `has_pending_dcr` is recomputed — false once no
    pending requests remain — and the request's `version` increments."

    Design: Difficulty/transitive_cascade/dcr_apply_employee_mutation_cancels_sibling_dcr
    """
    employee, d1, d2 = _employee_with_pending_address_and_deposit(api)

    approve_dcr(d1["id"])

    sibling = get_dcr(d2["id"])
    assert sibling["approval_status"] == "CANCELLED", (
        "the sibling pending request must be cancelled by the profile mutation"
    )

    profile = validate_success(api.get_employee(employee["id"], ADMIN))
    assert profile["has_pending_dcr"] is False


# ---------------------------------------------------------------------------
# Fraud lockout
# ---------------------------------------------------------------------------

def test_fraud_lockout_after_three_failures(api):
    """PRD §3.7: "A third failed attempt locks everything: the verification and the
    request's `fraud_status` both move to `LOCKED`, the request's `approval_status`
    is driven to `REJECTED` with its `reject_reason` set to
    `FRAUD_VERIFICATION_LOCKED`, and the employee's `has_pending_dcr` is recomputed."
    PRD §3.7: "Any verify call against an already-locked verification fails with
    `ERR_FRAUD_VERIFICATION_LOCKED`, raised at state-check priority ahead of the
    generic `ERR_DCR_INVALID_STATE` — so a locked request reports its lock, not a
    bare state error."

    Design: Corner/validations/fraud_lockout_after_three_failures
    """
    employee, dcr = _deposit_dcr_pending_verification(
        api, employee_number="E304", full_name="Loc Kout", email="lock@x.com"
    )

    for _ in range(3):
        resp = verify_dcr(dcr["id"], "SECURITY_CODE", employee["id"], evidence_code="BAD000")
        validate_error(resp, ApiErrorId.ERR_FRAUD_EVIDENCE_MISMATCH.value)

    locked_dcr = get_dcr(dcr["id"])
    assert locked_dcr["approval_status"] == "REJECTED"
    assert locked_dcr["fraud_status"] == "LOCKED"
    assert locked_dcr["reject_reason"] == "FRAUD_VERIFICATION_LOCKED"

    fv = fraud_verification_of(dcr["id"], employee["id"])
    assert fv["attempts"] == 3
    assert fv["status"] == "LOCKED"

    resp4 = verify_dcr(dcr["id"], "SECURITY_CODE", employee["id"], evidence_code="BAD000")
    validate_error(resp4, ApiErrorId.ERR_FRAUD_VERIFICATION_LOCKED.value)


# ---------------------------------------------------------------------------
# Approval gates and segregation of duties
# ---------------------------------------------------------------------------

def test_approve_pending_verification_fraud_required(api):
    """PRD §3.7: "The fraud gate comes first: `fraud_status` must be `VERIFIED` or
    `NOT_REQUIRED`, and approving while verification is still `PENDING` or has
    `FAILED` fails with `ERR_FRAUD_VERIFICATION_REQUIRED` — a business-safety
    rejection, not a state error."

    Design: Corner/validations/approve_pending_verification_fraud_required
    """
    employee, dcr = _deposit_dcr_pending_verification(
        api, employee_number="E305", full_name="Gate Gina", email="gina@x.com"
    )

    resp = api.approve_data_change_request(dcr["id"], STEWARD)
    validate_error(resp, ApiErrorId.ERR_FRAUD_VERIFICATION_REQUIRED.value)

    after = get_dcr(dcr["id"])
    assert after["approval_status"] == "PENDING_VERIFICATION"


def test_self_approval_forbidden(api):
    """PRD §3.7: "The steward may not decide their own request — a caller whose
    `X-User-ID` equals the request's `employee_id` fails with
    `ERR_SELF_APPROVAL_FORBIDDEN`."
    PRD §2.11: "An employee may not approve or reject their own data change request
    (`ERR_SELF_APPROVAL_FORBIDDEN`)."

    Design: Corner/validations/self_approval_forbidden
    """
    employee = make_employee(employee_number="E306", full_name="Self Approve", email="self@x.com")
    dcr = create_dcr(employee["id"], "ADDRESS",
                     new_values={"address_line1": "3 C St", "city": "Reno",
                                 "region": "NV", "postal_code": "89501"})
    assert dcr["approval_status"] == "PENDING_APPROVAL"

    # A steward-role call whose operator id equals the requester's employee id.
    resp = api.approve_data_change_request(
        dcr["id"], make_steward_headers(employee["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN.value)


def test_verifier_cannot_approve(api):
    """PRD §3.7: "And the steward may not approve a request whose verification they
    personally satisfied — a caller equal to the verification's
    `verified_by_user_id` fails with `ERR_VERIFIER_CANNOT_APPROVE`."
    PRD §3.7: "Under `MANAGER_CONFIRMATION` the caller — acting in the `Employee`
    role — must be the subject employee's manager of record, meaning the caller's
    `X-User-ID` equals that employee's `manager_id`; anyone else is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/verifier_cannot_approve
    """
    manager = make_employee(employee_number="E307", full_name="Mgr Mary", email="mary@x.com")
    employee = make_employee(manager_id=manager["id"], employee_number="E308",
                             full_name="Emp Ed", email="ed@x.com")
    dcr = create_dcr(employee["id"], "DIRECT_DEPOSIT",
                     new_values={"bank_routing_number": "021000021",
                                 "bank_account_number": "444444444",
                                 "bank_account_type": "CHECKING"})

    verified = validate_success(
        verify_dcr(dcr["id"], "MANAGER_CONFIRMATION", manager["id"])
    )
    assert verified["fraud_status"] == "VERIFIED"
    assert verified["approval_status"] == "PENDING_APPROVAL"

    # The manager who satisfied the verification may not approve the same request.
    resp = api.approve_data_change_request(dcr["id"], make_steward_headers(manager["id"]))
    validate_error(resp, ApiErrorId.ERR_VERIFIER_CANNOT_APPROVE.value)

    after = get_dcr(dcr["id"])
    assert after["approval_status"] == "PENDING_APPROVAL"


def test_manager_confirmation_by_non_manager_forbidden(api):
    """PRD §3.7: "Under `MANAGER_CONFIRMATION` the caller — acting in the `Employee`
    role — must be the subject employee's manager of record, meaning the caller's
    `X-User-ID` equals that employee's `manager_id`; anyone else is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/validations/manager_confirmation_by_non_manager_forbidden
    """
    manager = make_employee(employee_number="E309", full_name="Mgr Mo", email="mo@x.com")
    employee = make_employee(manager_id=manager["id"], employee_number="E310",
                             full_name="Emp Eli", email="eli2@x.com")
    other = make_employee(employee_number="E311", full_name="Other Olga", email="olga@x.com")
    dcr = create_dcr(employee["id"], "DIRECT_DEPOSIT",
                     new_values={"bank_routing_number": "021000021",
                                 "bank_account_number": "333333333",
                                 "bank_account_type": "SAVINGS"})

    resp = verify_dcr(dcr["id"], "MANAGER_CONFIRMATION", other["id"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    after = get_dcr(dcr["id"])
    assert after["fraud_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Uniqueness and optimistic concurrency
# ---------------------------------------------------------------------------

def test_duplicate_pending_dcr_same_type_rejected(api):
    """PRD §3.7: "Two business gates apply at submission: the subject employee must
    be `ACTIVE` — submitting while `ON_LEAVE` or `TERMINATED` fails with
    `ERR_EMPLOYEE_INACTIVE` — and an employee may hold only one pending request per
    change type, so a second submission of the same type while one is
    `PENDING_VERIFICATION` or `PENDING_APPROVAL` fails with
    `ERR_DUPLICATE_DATA_CHANGE_PENDING`."

    Design: Corner/validations/duplicate_pending_dcr_same_type_rejected
    """
    employee = make_employee(employee_number="E303", full_name="Dup Dcr", email="dup@x.com")
    create_dcr(employee["id"], "ADDRESS")  # now PENDING_APPROVAL

    resp = api.create_data_change_request(
        {
            "employee_id": employee["id"],
            "change_type": "ADDRESS",
            "new_values": {"address_line1": "2 B St", "city": "Boise",
                           "region": "ID", "postal_code": "83702"},
            "expected_employee_version": employee_version(employee["id"]),
        },
        make_employee_headers(employee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DATA_CHANGE_PENDING.value)


def test_occ_stale_employee_dcr_create_rejected(api):
    """PRD §2.9: "`POST /hr-helpdesk/data-change-requests` likewise requires the
    non-optional field `expected_employee_version`, carrying the caller's last
    observed `version` of the subject Employee. A mismatch with the employee's
    current `version` is rejected with `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412): the
    new request would edit values the caller could not have seen, because a sibling
    request may have just been created or applied, flipping `has_pending_dcr` or
    writing profile fields."

    Design: Corner/cross_cutting_layers/occ_stale_employee_dcr_create_rejected
    """
    employee = make_employee(employee_number="E602", full_name="Occ Emp", email="occe@x.com")
    stale_version = employee["version"]
    d1 = create_dcr(employee["id"], "ADDRESS",
                    new_values={"address_line1": "5 E St", "city": "Mesa",
                                "region": "AZ", "postal_code": "85201"},
                    expected_employee_version=stale_version)
    assert d1["id"]

    resp = api.create_data_change_request(
        {
            "employee_id": employee["id"],
            "change_type": "DIRECT_DEPOSIT",
            "new_values": {"bank_routing_number": "021000021",
                           "bank_account_number": "222222222",
                           "bank_account_type": "CHECKING"},
            "expected_employee_version": stale_version,
        },
        make_employee_headers(employee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_EMPLOYEE_VERSION.value)

    _data, meta = validate_paginated(
        api.list_data_change_requests(STEWARD, params={"employee_id": employee["id"]})
    )
    assert meta["total_count"] == 1, "only the first DCR may exist for the employee"


# ---------------------------------------------------------------------------
# Employee-active gate (cross-entity dependency)
# ---------------------------------------------------------------------------

def _on_leave_employee(api, employee_number="E130", full_name="Lou Leave", email="lou@x.com"):
    employee = make_employee(employee_number=employee_number, full_name=full_name, email=email)
    set_employee_status(employee["id"], "ON_LEAVE")
    return employee


def test_dcr_create_for_on_leave_employee_rejected(api):
    """PRD §3.7: "Two business gates apply at submission: the subject employee must
    be `ACTIVE` — submitting while `ON_LEAVE` or `TERMINATED` fails with
    `ERR_EMPLOYEE_INACTIVE` — and an employee may hold only one pending request per
    change type, so a second submission of the same type while one is
    `PENDING_VERIFICATION` or `PENDING_APPROVAL` fails with
    `ERR_DUPLICATE_DATA_CHANGE_PENDING`."

    Design: Difficulty/cross_entity_state_dependency/dcr_create_requires_active_employee
    """
    employee = _on_leave_employee(api)

    resp = api.create_data_change_request(
        {
            "employee_id": employee["id"],
            "change_type": "ADDRESS",
            "new_values": {"address_line1": "9 B St", "city": "Provo",
                           "region": "UT", "postal_code": "84601"},
            "expected_employee_version": employee_version(employee["id"]),
        },
        make_employee_headers(employee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_INACTIVE.value)


def test_rejected_dcr_create_persists_nothing(api):
    """PRD §3.7: "Two business gates apply at submission: the subject employee must
    be `ACTIVE` — submitting while `ON_LEAVE` or `TERMINATED` fails with
    `ERR_EMPLOYEE_INACTIVE` — and an employee may hold only one pending request per
    change type, so a second submission of the same type while one is
    `PENDING_VERIFICATION` or `PENDING_APPROVAL` fails with
    `ERR_DUPLICATE_DATA_CHANGE_PENDING`."
    PRD §3.7: "Requests are listed with the `employee_id`, `approval_status`, and
    `change_type` filters — employees see only their own — and any
    state-incompatible action fails with `ERR_DCR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/dcr_create_requires_active_employee
    """
    employee = _on_leave_employee(api)

    resp = api.create_data_change_request(
        {
            "employee_id": employee["id"],
            "change_type": "ADDRESS",
            "new_values": {"address_line1": "9 B St", "city": "Provo",
                           "region": "UT", "postal_code": "84601"},
            "expected_employee_version": employee_version(employee["id"]),
        },
        make_employee_headers(employee["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_INACTIVE.value)

    _data, meta = validate_paginated(
        api.list_data_change_requests(STEWARD, params={"employee_id": employee["id"]})
    )
    assert meta["total_count"] == 0, "a rejected submission must not persist a request"


# ---------------------------------------------------------------------------
# Validation-order pair: state (tier 6) beats business safety (tier 7)
# ---------------------------------------------------------------------------

def _rejected_dcr_then_terminated_employee(api):
    employee = make_employee(employee_number="E800", full_name="Pam Prio", email="pam@x.com")
    dcr = create_dcr(employee["id"], "ADDRESS",
                     new_values={"address_line1": "1 A St", "city": "Boise",
                                 "region": "ID", "postal_code": "83701"})
    assert dcr["approval_status"] == "PENDING_APPROVAL"
    rejected = validate_success(
        api.reject_data_change_request(dcr["id"], {"reason": "insufficient evidence"}, STEWARD)
    )
    assert rejected["approval_status"] == "REJECTED"
    set_employee_status(employee["id"], "TERMINATED")
    return employee, dcr


def test_approve_rejected_dcr_reports_state_error(api):
    """PRD §2.10: "When several checks could reject the same request, they are
    evaluated in the following fixed order, and the earliest failing tier determines
    the response:"
    PRD §2.10: "6. **State.** The target entity must sit in a from-state of the
    requested transition. Failures: `ERR_TICKET_INVALID_STATE`,
    `ERR_DCR_INVALID_STATE`, `ERR_ARTICLE_INVALID_STATE`, `ERR_SURVEY_INVALID_STATE`,
    `ERR_WINDOW_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, or
    `ERR_EMPLOYEE_INVALID_STATE` (all 409)."
    PRD §2.10: "7. **Business safety.** Confidentiality clearance on writes to
    sensitive tickets (`ERR_CONFIDENTIALITY_CLEARANCE_REQUIRED`, 403); the fraud gate
    on approval (`ERR_FRAUD_VERIFICATION_REQUIRED`, 409); the employee-active gate on
    data change creation and approval (`ERR_EMPLOYEE_INACTIVE`, 422); and the
    segregation-of-duties rules (`ERR_AUTHOR_CANNOT_PUBLISH`,
    `ERR_SELF_APPROVAL_FORBIDDEN`, `ERR_VERIFIER_CANNOT_APPROVE`, all 403)."

    Design: Difficulty/priority_pair_validation_conflict/approve_rejected_dcr_terminated_employee_state_beats_safety
    """
    _employee, dcr = _rejected_dcr_then_terminated_employee(api)

    # The DCR is REJECTED (tier 6) AND the employee is TERMINATED (tier 7):
    # the state error must surface.
    resp = api.approve_data_change_request(dcr["id"], STEWARD2)
    validate_error(resp, ApiErrorId.ERR_DCR_INVALID_STATE.value)


def test_approve_rejected_dcr_leaves_request_unchanged(api):
    """PRD §3.7: "The request's terminal states are `APPLIED`, `REJECTED`, and
    `CANCELLED`, and the fraud dimension settles permanently at `NOT_REQUIRED`,
    `VERIFIED`, or `LOCKED`."
    PRD §2.10: "6. **State.** The target entity must sit in a from-state of the
    requested transition. Failures: `ERR_TICKET_INVALID_STATE`,
    `ERR_DCR_INVALID_STATE`, `ERR_ARTICLE_INVALID_STATE`, `ERR_SURVEY_INVALID_STATE`,
    `ERR_WINDOW_INVALID_STATE`, `ERR_SHIFT_INVALID_STATE`, or
    `ERR_EMPLOYEE_INVALID_STATE` (all 409)."

    Design: Difficulty/priority_pair_validation_conflict/approve_rejected_dcr_terminated_employee_state_beats_safety
    """
    _employee, dcr = _rejected_dcr_then_terminated_employee(api)

    resp = api.approve_data_change_request(dcr["id"], STEWARD2)
    validate_error(resp, ApiErrorId.ERR_DCR_INVALID_STATE.value)

    after = get_dcr(dcr["id"])
    assert after["approval_status"] == "REJECTED", "a terminal request must not move"
