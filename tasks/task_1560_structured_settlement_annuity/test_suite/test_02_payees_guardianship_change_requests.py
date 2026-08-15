"""Payee registration, minority computation, guardianship intervals, and change
requests (PRD §3.1, §3.5)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_profile, create_payee, setup_active_case, issue_and_return,
    create_guardianship_case_payload, create_payee_change_request_payload,
    set_clock, get_payee, get_guardianship_case,
    TEST_USERS,
    make_case_manager_headers, make_compliance_officer_headers, make_payee_headers,
    assert_payee,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CASE_MGR = TEST_USERS["case_manager_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
READER = TEST_USERS["reader_headers"]


# --- Payee registration (PRD §3.1) --------------------------------------------

def test_payee_creation_applies_defaults(api):
    """PRD §3.1: "A new payee starts `ACTIVE` with `deceased_date` null."
    PRD §3.1: "`is_minor` is true exactly when that age is strictly less than the
    residence profile's `age_of_majority`".

    Design: Corner/entities/payee_creation_applies_defaults
    """
    create_profile()
    payee = create_payee(full_name="Nora New", date_of_birth="1980-06-15",
                         tax_id="121-12-1212")
    assert_payee(payee)
    assert payee["status"] == "ACTIVE"
    assert payee["deceased_date"] is None
    # Age 46 at the default clock (2026-08-01) against an 18-year majority.
    assert payee["is_minor"] is False


def test_payee_missing_tax_id_returns_invalid_request(api):
    """PRD §2.10: "Input shape last: required fields present, enum members valid, date
    strings in the required form, cents fields positive where required, a payment's
    `due_date` not earlier than its schedule's `effective_from_date`, `transfer_end_date`
    not earlier than `transfer_start_date`, and no unknown payload fields — all rejected
    as `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "a `CaseManager` registers each injured party as a `Payee` with
    `full_name`, `date_of_birth` (strictly before the current clock date), `tax_id`
    for 1099 reporting".

    Design: Corner/entities/payee_missing_tax_id_returns_invalid_request
    """
    create_profile()
    payload = {
        "full_name": "Nora New", "date_of_birth": "1980-06-15",
        "address_line1": "12 First St", "address_city": "Riverside",
        "address_state_code": "CA", "address_postal_code": "92501",
    }
    resp = api.create_payee(payload, CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_duplicate_state_profile_rejected(api):
    """PRD §2.8: "Registering a second profile for a state code that already has one
    fails with `ERR_DUPLICATE_STATE_PROFILE` (HTTP 409)."

    Design: Corner/entities/duplicate_state_profile_rejected
    """
    create_profile()
    resp = api.create_state_profile(
        {"state_code": "CA", "age_of_majority": 19, "sspa_max_discount_rate_bps": 800,
         "disclosure_cooling_off_days": 5, "ipa_required": False,
         "dormancy_years": 2, "commutation_permitted": False}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STATE_PROFILE)
    # A different state code remains registrable.
    other = validate_success(api.create_state_profile(
        {"state_code": "NV", "age_of_majority": 18, "sspa_max_discount_rate_bps": 900,
         "disclosure_cooling_off_days": 14, "ipa_required": True,
         "dormancy_years": 3, "commutation_permitted": True}, ADMIN), 201)
    assert other["state_code"] == "NV"


def test_minority_boundary_at_majority_birthday(api):
    """PRD §3.1: "`is_minor` is true exactly when that age is strictly less than the
    residence profile's `age_of_majority` — on the majority birthday itself the payee
    is no longer a minor."

    Design: Corner/entities/minority_boundary_at_majority_birthday
    """
    create_profile()
    payee = create_payee(full_name="Maya Minor", date_of_birth="2010-05-15",
                         tax_id="141-14-1414")
    # Age 16 at the default clock 2026-08-01.
    assert payee["is_minor"] is True

    set_clock("2028-05-14T00:00:00Z")
    before = get_payee(payee["id"])
    assert before["is_minor"] is True, "2028-05-14: the 18th birthday has not yet occurred"

    set_clock("2028-05-15T00:00:00Z")
    on_day = get_payee(payee["id"])
    assert on_day["is_minor"] is False, "2028-05-15: the exact majority birthday flips the flag"


# --- Guardianship (PRD §3.1) ----------------------------------------------------

def test_guardianship_auto_terminates_at_majority(api):
    """PRD §3.1: "On every clock-set, a payee who has reached the residence profile's
    `age_of_majority` — the clock date on or after the majority birthday — has the case
    moved `ACTIVE` → `TERMINATED` with `terminated_at_date` set to the majority birthday
    itself."

    Design: Corner/state_machines/guardianship_auto_terminates_at_majority
    """
    create_profile()
    payee = create_payee(full_name="Maya Minor", date_of_birth="2010-05-15",
                         tax_id="141-14-1414")
    case = validate_success(api.create_guardianship_case(
        create_guardianship_case_payload(payee["id"]), CASE_MGR), 201)
    case = validate_success(api.activate_guardianship_case(case["id"], COMPLIANCE))
    assert case["status"] == "ACTIVE"

    set_clock("2028-05-14T00:00:00Z")
    before = get_guardianship_case(case["id"])
    assert before["status"] == "ACTIVE", "day before the majority birthday: still ACTIVE"

    set_clock("2028-05-15T00:00:00Z")
    on_day = get_guardianship_case(case["id"])
    assert on_day["status"] == "TERMINATED"
    assert on_day["terminated_at_date"] == "2028-05-15"


def test_guardianship_activate_twice_returns_invalid_state(api):
    """PRD §3.1: "Cases begin `PENDING_REVIEW` and are activated by a `ComplianceOfficer`
    once the court order is reviewed: `PENDING_REVIEW` → `ACTIVE`, with
    `ERR_GUARDIANSHIP_INVALID_STATE` greeting an activation attempt on a case in any
    other state."

    Design: Corner/errors/guardianship_activate_twice_returns_invalid_state
    """
    create_profile()
    payee = create_payee()
    case = validate_success(api.create_guardianship_case(
        create_guardianship_case_payload(payee["id"]), CASE_MGR), 201)
    validate_success(api.activate_guardianship_case(case["id"], COMPLIANCE))
    resp = api.activate_guardianship_case(case["id"], COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_GUARDIANSHIP_INVALID_STATE)


def test_open_ended_active_guardianship_blocks_overlapping_create(api):
    """PRD §3.1: "Both at creation and again at activation, the system rejects overlap
    with `ERR_GUARDIANSHIP_OVERLAP` when any other `PENDING_REVIEW` or `ACTIVE` case for
    the same payee has an interval intersecting the new case's interval."
    PRD §3.1: "a case governs from `effective_from_date` up to but not including
    `terminated_at_date`, which is null while the appointment is open-ended and is then
    treated as infinity."

    Design: Difficulty/resource_temporal_overlap/guardianship_half_open_interval_overlap
    """
    create_profile()
    payee = create_payee(full_name="Hal Fopen", date_of_birth="1990-04-02",
                         tax_id="707-07-0707")
    case1 = validate_success(api.create_guardianship_case(
        create_guardianship_case_payload(payee["id"], guardian_full_name="G One",
                                         effective_from_date="2026-01-01"), CASE_MGR), 201)
    case1 = validate_success(api.activate_guardianship_case(case1["id"], COMPLIANCE))
    assert case1["status"] == "ACTIVE"

    # case1's interval is open-ended: [2026-01-01, infinity) swallows 2026-06-01.
    resp = api.create_guardianship_case(
        create_guardianship_case_payload(payee["id"], guardian_full_name="G Two",
                                         effective_from_date="2026-06-01"), CASE_MGR)
    validate_error(resp, ApiErrorId.ERR_GUARDIANSHIP_OVERLAP)


def test_guardianship_starting_on_revocation_date_is_allowed(api):
    """PRD §3.1: "Revocation by a `ComplianceOfficer` requires an `ACTIVE` case
    (`ERR_GUARDIANSHIP_INVALID_STATE` otherwise) and moves it `ACTIVE` → `REVOKED`,
    stamping `terminated_at_date` with the current clock date."
    PRD §3.1: "a case governs from `effective_from_date` up to but not including
    `terminated_at_date`".

    Design: Difficulty/resource_temporal_overlap/guardianship_half_open_interval_overlap
    """
    create_profile()
    payee = create_payee(full_name="Hal Fopen", date_of_birth="1990-04-02",
                         tax_id="707-07-0707")
    case1 = validate_success(api.create_guardianship_case(
        create_guardianship_case_payload(payee["id"], guardian_full_name="G One",
                                         effective_from_date="2026-01-01"), CASE_MGR), 201)
    validate_success(api.activate_guardianship_case(case1["id"], COMPLIANCE))

    set_clock("2026-12-31T00:00:00Z")
    revoked = validate_success(api.revoke_guardianship_case(case1["id"], COMPLIANCE))
    assert revoked["status"] == "REVOKED"
    assert revoked["terminated_at_date"] == "2026-12-31"

    # Half-open end is exclusive and REVOKED cases are excluded from the overlap check.
    case3 = validate_success(api.create_guardianship_case(
        create_guardianship_case_payload(payee["id"], guardian_full_name="G Three",
                                         effective_from_date="2026-12-31"), CASE_MGR), 201)
    assert case3["status"] == "PENDING_REVIEW"


# --- Payee change requests (PRD §3.5) ---------------------------------------------

def test_change_request_auto_approves_without_open_case(api):
    """PRD §3.5: "An `ADDRESS` request auto-approves — moving straight from `SUBMITTED`
    to `APPROVED`, overwriting the payee's address fields with the new values and bumping
    the payee's `version` — but only when no returned-payment case in `OPEN` or
    `ESCHEAT_PENDING` status exists for any of the payee's scheduled payments".

    Design: Corner/state_machines/change_request_auto_approves_without_open_case
    """
    create_profile()
    create_profile(state_code="NV", sspa_max_discount_rate_bps=900,
                   disclosure_cooling_off_days=14)
    payee = create_payee(full_name="Ada Move", date_of_birth="1979-07-07",
                         tax_id="212-12-1212")
    version_before = payee["version"]

    request = validate_success(api.create_payee_change_request(
        create_payee_change_request_payload(
            payee["id"], "ADDRESS", new_address_line1="77 Sierra Way",
            new_address_city="Reno", new_address_state_code="NV",
            new_address_postal_code="89501"),
        make_payee_headers(payee["id"])), 201)
    assert request["status"] == "APPROVED", "no open returned-payment case: auto-approved"

    payee_after = get_payee(payee["id"])
    assert payee_after["address_state_code"] == "NV"
    assert payee_after["address_line1"] == "77 Sierra Way"
    assert payee_after["version"] == version_before + 1, (
        "the auto-approve bumps the payee's version once"
    )


def test_change_request_under_review_then_approve_with_open_case(api):
    """PRD §3.5: "an open investigation routes the request to human review instead,
    since the address itself is suspect."
    PRD §3.5: "A `ComplianceOfficer` then approves or rejects: both actions require the
    request `UNDER_REVIEW` (`ERR_CHANGE_REQUEST_INVALID_STATE`)".

    Design: Corner/state_machines/change_request_under_review_then_approve_with_open_case
    """
    ctx = setup_active_case(
        payments=[{"due_date": "2026-08-10", "base_amount_cents": 50000}],
        clock_to="2026-08-10T00:00:00Z")
    payment = ctx["payments"][0]
    issue_and_return(payment["id"], method="CHECK", user_id="ops-1")

    request = validate_success(api.create_payee_change_request(
        create_payee_change_request_payload(
            ctx["payee"]["id"], "ADDRESS", new_address_line1="99 New St",
            new_address_city="Stockton", new_address_state_code="CA",
            new_address_postal_code="95203"),
        make_case_manager_headers("cm-1")), 201)
    assert request["status"] == "UNDER_REVIEW", (
        "an OPEN returned-payment case blocks the auto-approval"
    )

    approved = validate_success(api.approve_change_request(
        request["id"], make_compliance_officer_headers("co-1")))
    assert approved["status"] == "APPROVED"
    assert get_payee(ctx["payee"]["id"])["address_line1"] == "99 New St"


def test_approve_already_approved_change_returns_invalid_state(api):
    """PRD §3.5: "A `ComplianceOfficer` then approves or rejects: both actions require
    the request `UNDER_REVIEW` (`ERR_CHANGE_REQUEST_INVALID_STATE`)".

    Design: Corner/errors/approve_already_approved_change_returns_invalid_state
    """
    create_profile()
    create_profile(state_code="NV", sspa_max_discount_rate_bps=900,
                   disclosure_cooling_off_days=14)
    payee = create_payee()
    request = validate_success(api.create_payee_change_request(
        create_payee_change_request_payload(
            payee["id"], "ADDRESS", new_address_line1="88 Desert Rd",
            new_address_city="Reno", new_address_state_code="NV",
            new_address_postal_code="89502"),
        make_payee_headers(payee["id"])), 201)
    assert request["status"] == "APPROVED", "auto-approved at creation"

    resp = api.approve_change_request(request["id"], make_compliance_officer_headers("co-1"))
    validate_error(resp, ApiErrorId.ERR_CHANGE_REQUEST_INVALID_STATE)


def test_sod_change_request_staff_submitter_cannot_approve(api):
    """PRD §3.5: "`NAME` and `BANK_ACCOUNT` requests always land `UNDER_REVIEW`."
    PRD §3.5: "approval additionally enforces segregation of duties — the approver's
    `X-User-ID` must differ from `submitted_by_user_id` (`ERR_SOD_VIOLATION`)."

    Design: Corner/rbac/sod_change_request_staff_submitter_cannot_approve
    """
    create_profile()
    payee = create_payee(full_name="Banks Ty", date_of_birth="1990-02-02",
                         tax_id="464-65-6767")
    request = validate_success(api.create_payee_change_request(
        create_payee_change_request_payload(
            payee["id"], "BANK_ACCOUNT", new_bank_routing_number="121000358",
            new_bank_account_number="99887766"),
        make_case_manager_headers("cm-1")), 201)
    assert request["status"] == "UNDER_REVIEW", "BANK_ACCOUNT never auto-approves"

    resp = api.approve_change_request(request["id"], make_compliance_officer_headers("cm-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

    approved = validate_success(api.approve_change_request(
        request["id"], make_compliance_officer_headers("co-9")))
    assert approved["status"] == "APPROVED"
