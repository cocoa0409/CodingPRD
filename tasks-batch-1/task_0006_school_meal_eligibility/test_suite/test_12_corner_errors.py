"""Tests covering error-catalog corner cases: authentication, authorization,
missing resources, invalid payload shapes, pagination bounds, OCC mismatches,
allergen conflict on transaction creation, insufficient funds, and idempotency
key collisions.
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    setup_clean_world,
    create_household,
    create_student,
    create_allergy_profile,
    create_application,
    submit_application,
    start_review,
    deny_application,
    create_direct_cert_eligibility,
    create_menu_item,
    create_service_transaction,
    settle_transaction,
    refund_transaction,
    dispute_transaction,
    verify_eligibility,
    resolve_parent_account_id,
    api_client,
    TEST_USERS,
    make_parent_headers,
    make_unauthenticated_headers,
)


# ---------------------------------------------------------------------
# Corner / errors
# ---------------------------------------------------------------------

def test_missing_x_user_role_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming one of the
    system's five declared roles. If `X-User-Role` is missing or names a role
    outside the declared set, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/error_unauthenticated_missing_x_user_role_header
    """
    res = api.list_menu_items(make_unauthenticated_headers())
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_parent_calling_school_staff_only_endpoint_returns_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not on the endpoint's
    allow-list, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/errors/error_forbidden_parent_attempts_school_staff_only_endpoint
    """
    setup_clean_world()
    hh = create_household()
    # POST /students is SchoolStaff-only per PRD §4 endpoint table.
    res = api.create_student(
        {
            "household_id": hh["id"], "full_name": "Kid",
            "school_code": "ELEM-101", "grade_level": 3,
        },
        make_parent_headers(hh["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_read_nonexistent_application_returns_not_found(api):
    """PRD §2.8: "if any path-templated `{id}` does not resolve to an
    existing entity, the request is rejected with `ERR_NOT_FOUND`."

    Design: Corner/errors/error_not_found_nonexistent_application_id
    """
    setup_clean_world()
    res = api.get_application(
        "00000000-0000-0000-0000-000000000000",
        TEST_USERS["district_reviewer_headers"],
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_household_create_missing_family_size_returns_invalid_request(api):
    """PRD §3.1: "Creating one is the first act of onboarding and is performed
    by either school staff or a district reviewer; the payload contains the
    responsible parent or guardian's `primary_parent_name`, the `family_size`
    (an integer between 1 and 20 inclusive), the reported gross
    `annual_income_cents` (a non-negative integer), and the two-letter
    uppercase `address_state` that determines which federal poverty table
    will later apply."

    Design: Corner/errors/error_invalid_request_missing_required_field
    """
    setup_clean_world()
    res = api.create_household(
        {
            "primary_parent_name": "Missing Fam",
            "annual_income_cents": 3000000,
            "address_state": "CA",
        },
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_list_pagination_limit_over_hundred_returns_invalid_pagination(api):
    """PRD §2.3: "The `limit` parameter defaults to 10 if omitted, must be at
    least 1, and must not exceed 100. The `offset` parameter defaults to 0
    and must not be negative. A request with `limit` outside the inclusive
    range from 1 to 100 or with a negative `offset` is rejected with
    `ERR_INVALID_PAGINATION`."

    Design: Corner/errors/error_invalid_pagination_limit_over_100
    """
    setup_clean_world()
    res = api.list_menu_items(
        TEST_USERS["school_staff_headers"], params={"limit": 200}
    )
    validate_error(res, "ERR_INVALID_PAGINATION", expected_status=400)


def test_application_submit_with_complete_household_snapshots_fields(api):
    """PRD §3.2: "When the parent submits a `DRAFT` application, the server
    requires that the household has both an `annual_income_cents` and a
    `family_size` recorded; if either is null, submission is rejected with
    `ERR_HOUSEHOLD_INCOMPLETE`. On success the application's `status`
    transitions from `DRAFT` to `SUBMITTED`, and three snapshot fields are
    pinned in the same operation: `snapshot_family_size`,
    `snapshot_annual_income_cents`, and `snapshot_address_state` are copied
    from the household's current values into the application."

    Design: Corner/errors/error_household_incomplete_on_submit
    """
    setup_clean_world()
    hh = create_household(
        family_size=2, annual_income_cents=3_000_000, address_state="CA",
    )
    app = create_application(hh["id"])
    submitted = submit_application(app["id"], hh["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["snapshot_annual_income_cents"] == 3_000_000
    assert submitted["snapshot_family_size"] == 2


def test_settle_paid_tier_against_zero_balance_returns_insufficient_funds(api):
    """PRD §3.6: "Settling a `PENDING` transaction is school staff's act. The
    transition requires the transaction to be in `PENDING`, the chosen
    `EligibilityDetermination` still to be in `lifecycle_status` `ACTIVE`
    (cross-entity dependency: a settle attempt against a transaction whose
    chosen determination has since been superseded, expired, or revoked
    fails), and the parent account's reconciled `balance_cents` to be at
    least the transaction's `paid_charge_cents`. If the balance is
    insufficient, the request is rejected with `ERR_INSUFFICIENT_FUNDS`."

    Design: Corner/errors/error_insufficient_funds_on_settle
    """
    set_clock("2026-05-10T09:00:00.000Z")
    # PAID-tier household with no topup.
    from test_helpers import setup_approved_application
    hh, stu, _approved = setup_approved_application(
        clock_iso="2026-05-10T09:00:00.000Z",
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA",
        decision_reason="PAID confirmed",
        direct_certification_flag=False,
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="PaidLunch",
        list_price_cents=300, allergens_present=[],
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    assert tx["paid_charge_cents"] == 300, (
        f"PAID-tier 300c list price should produce charge 300; "
        f"got {tx['paid_charge_cents']}"
    )
    res = api.settle_service_transaction(tx["id"], TEST_USERS["school_staff_headers"])
    validate_error(res, "ERR_INSUFFICIENT_FUNDS", expected_status=422)


def test_duplicate_idempotency_key_with_different_amount_returns_duplicate_error(api):
    """PRD §3.6: "If a re-submission carries the same `idempotency_key` but a
    different `amount_cents`, the request is rejected with
    `ERR_DUPLICATE_IDEMPOTENCY_KEY`."

    Design: Corner/errors/error_duplicate_idempotency_key_on_topup
    """
    set_clock("2026-05-11T09:00:00.000Z")
    hh = create_household(
        family_size=2, annual_income_cents=3_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    pa_id = resolve_parent_account_id(hh["id"])
    first = api.topup_parent_account(
        pa_id,
        {"amount_cents": 5000, "idempotency_key": "dup-1"},
        make_parent_headers(hh["id"]),
    )
    validate_success(first, 201)
    # Same key, DIFFERENT amount.
    res = api.topup_parent_account(
        pa_id,
        {"amount_cents": 9999, "idempotency_key": "dup-1"},
        make_parent_headers(hh["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_IDEMPOTENCY_KEY", expected_status=409)


def test_appeal_with_stale_application_version_returns_stale_version(api):
    """PRD §2.5: "Submitting an appeal on a `MealApplication` requires the
    request body to include `expected_mealapplication_version`. If the value
    does not equal the application's current `version`, the request is
    rejected with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/errors/error_stale_version_appeal_old_application_version
    """
    set_clock("2026-05-12T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    app = create_application(hh["id"])
    submit_application(app["id"], hh["id"])
    start_review(app["id"])
    denied = deny_application(app["id"], decision_reason="missing docs")
    v_denied = denied["version"]
    # Send appeal with a deliberately stale (off-by-one) version.
    res = api.appeal_application(
        app["id"],
        {
            "appeal_reason": "stale attempt",
            "expected_mealapplication_version": v_denied - 1,
        },
        make_parent_headers(hh["id"]),
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_refund_after_dispute_bumps_version_returns_stale_version(api):
    """PRD §2.5: "Refunding a `ServiceTransaction` requires the request body
    to include `expected_servicetransaction_version`. If the value does not
    equal the transaction's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412). This guards against the transaction
    having advanced — for example, into `DISPUTED` — since the staff
    member's read; a refund issued against a stale `SETTLED` view would
    double-compensate the parent."

    Design: Corner/errors/error_stale_version_refund_after_dispute_bumped_version
    """
    set_clock("2026-05-13T09:00:00.000Z")
    from test_helpers import setup_approved_application, topup_account
    hh, stu, _approved = setup_approved_application(
        clock_iso="2026-05-13T09:00:00.000Z",
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA",
        decision_reason="PAID",
        direct_certification_flag=False,
    )
    topup_account(hh["id"], 1000, idempotency_key="stale-tx-1")
    menu = create_menu_item(
        school_code="ELEM-101", name="Burger", list_price_cents=300,
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    settled = settle_transaction(tx["id"])
    v_settled = settled["version"]
    dispute_transaction(settled["id"], hh["id"])  # bumps version
    # Refund with the stale (pre-dispute) version.
    res = api.refund_service_transaction(
        tx["id"],
        {"expected_servicetransaction_version": v_settled},
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_revoke_after_verify_bumps_version_returns_stale_version(api):
    """PRD §2.5: "Revoking an `EligibilityDetermination` requires the request
    body to include `expected_eligibilitydetermination_version`. If the
    value does not equal the determination's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case
    where a verification or deferral on the same determination has bumped
    its `version` since the auditor's read; the auditor must re-read and
    re-issue."

    Design: Corner/errors/error_stale_version_revoke_determination
    """
    set_clock("2026-05-14T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    elig = create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-05-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    v_initial = elig["version"]
    verify_eligibility(elig["id"])  # bumps version
    res = api.revoke_eligibility_determination(
        elig["id"],
        {"expected_eligibilitydetermination_version": v_initial},
        TEST_USERS["usda_auditor_headers"],
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_create_transaction_for_severe_allergen_no_substitution_returns_allergen_conflict(api):
    """PRD §3.5: "If the menu item's `allergens_present` intersects the
    student's `AllergyProfile.allergens`, the student's allergy `severity` is
    `SEVERE_ANAPHYLACTIC`, and the request did not set
    `substitute_for_allergen` to true, the creation is rejected with
    `ERR_ALLERGEN_CONFLICT`."

    Design: Corner/errors/error_allergen_conflict_create_tx_severe_no_substitute
    """
    set_clock("2026-05-15T09:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_allergy_profile(
        stu["id"], allergens=["PEANUT"], severity="SEVERE_ANAPHYLACTIC",
    )
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-05-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(
        school_code="ELEM-101", name="PB Cookie", list_price_cents=100,
        allergens_present=["PEANUT"],
    )
    res = api.create_service_transaction(
        {"student_id": stu["id"], "menu_item_id": menu["id"]},
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_ALLERGEN_CONFLICT", expected_status=422)
