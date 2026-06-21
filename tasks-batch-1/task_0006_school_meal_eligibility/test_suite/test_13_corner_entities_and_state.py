"""Tests covering CRUD-level corner cases on entities (creation, defaults,
computed fields, initial system fields, type constraints) and state-machine
invariants (invalid transitions, terminal locks, automatic transitions).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_clean_world,
    create_household,
    create_student,
    create_application,
    create_direct_cert_eligibility,
    create_menu_item,
    create_service_transaction,
    reject_transaction,
    submit_application,
    start_review,
    advance_clock_and_expire,
    topup_account,
    resolve_parent_account_id,
    api_client,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Corner / entities
# ---------------------------------------------------------------------

def test_create_household_returns_201_and_default_direct_certification_false(api):
    """PRD §3.1: "The payload may also set `direct_certification_flag`, which
    defaults to false and asserts that the household is enrolled in SNAP,
    TANF, or FDPIR and is therefore automatically eligible for free meals
    without ever filing an application."
    PRD §2.4: "The `version` field is a non-negative integer that increments
    by exactly one on every mutation and is the input to optimistic
    concurrency control (§2.5)."

    Design: Corner/entities/creation_household_201_with_required_fields
    """
    setup_clean_world()
    res = api.create_household(
        {
            "primary_parent_name": "Init",
            "family_size": 3,
            "annual_income_cents": 4_000_000,
            "address_state": "TX",
        },
        TEST_USERS["school_staff_headers"],
    )
    data = validate_success(res, 201)
    assert data["version"] == 1
    assert data["direct_certification_flag"] is False


def test_allergy_profile_defaults_empty_allergens_and_mild_severity(api):
    """PRD §3.1: "If `allergens` is omitted, it defaults to an empty array;
    if `severity` is omitted, it defaults to `MILD`."

    Design: Corner/entities/default_allergy_profile_empty_allergens_and_mild_severity
    """
    setup_clean_world()
    hh = create_household()
    stu = create_student(hh["id"], school_code="ELEM-101")
    res = api.create_allergy_profile(
        {"student_id": stu["id"]},
        TEST_USERS["school_staff_headers"],
    )
    data = validate_success(res, 201)
    assert data["allergens"] == [], (
        f"omitted allergens must default to []; got {data['allergens']!r}"
    )
    assert data["severity"] == "MILD", (
        f"omitted severity must default to MILD; got {data['severity']!r}"
    )


def test_parent_account_balance_reflects_topup_via_ledger_sum(api):
    """PRD §2.9: "Its `balance_cents` is never written directly; it is a
    derived field equal to the signed sum over the account's `LedgerEntry`
    rows. Every change to the balance — a top-up, a meal charge, a refund,
    or an adjustment — happens by creating a new ledger entry. The balance
    shown on a read of a `ParentAccount` is reconciled from the ledger."

    Design: Corner/entities/computed_parent_account_balance_from_ledger_after_topup
    """
    set_clock("2026-06-01T09:00:00.000Z")
    hh = create_household()
    pa_id = resolve_parent_account_id(hh["id"])
    topup_account(hh["id"], 5000, idempotency_key="bal-1", parent_account_id=pa_id)
    res = api.get_parent_account(pa_id, make_parent_headers(hh["id"]))
    data = validate_success(res, 200)
    assert data["balance_cents"] == 5000, (
        f"after one 5000c TOPUP, balance_cents must be 5000; "
        f"got {data['balance_cents']}"
    )


def test_meal_application_initial_status_is_draft(api):
    """PRD §3.2: "A `MealApplication` carries the household through the
    formal FRL determination path. It is created in `DRAFT` against a
    `household_id` and a `school_year` label such as `2025-2026`".

    Design: Corner/entities/system_fields_application_initial_status_is_draft
    """
    setup_clean_world()
    hh = create_household()
    res = api.create_application(
        {"household_id": hh["id"], "school_year": "2025-2026"},
        make_parent_headers(hh["id"]),
    )
    data = validate_success(res, 201)
    assert data["status"] == "DRAFT"


def test_allergy_profile_invalid_severity_enum_returns_invalid_request(api):
    """PRD §3.1: "an overall `severity` of `MILD`, `MODERATE`, or
    `SEVERE_ANAPHYLACTIC`."

    Design: Corner/entities/type_constraints_invalid_severity_enum
    """
    setup_clean_world()
    hh = create_household()
    stu = create_student(hh["id"], school_code="ELEM-101")
    res = api.create_allergy_profile(
        {"student_id": stu["id"], "allergens": ["PEANUT"], "severity": "SEVERE"},
        TEST_USERS["school_staff_headers"],
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ---------------------------------------------------------------------
# Corner / state_machines
# ---------------------------------------------------------------------

def test_approve_application_from_draft_returns_invalid_state(api):
    """PRD §3.2: "From `UNDER_REVIEW` only a district reviewer may decide the
    outcome: approval, which transitions the application to `APPROVED` and
    produces an `EligibilityDetermination` (described below); or denial,
    which transitions to `DENIED`."
    PRD §2.10: "then the state-machine precondition for any state-mutating
    operation".

    Design: Corner/state_machines/invalid_transition_approve_from_draft
    """
    setup_clean_world()
    hh = create_household()
    app = create_application(hh["id"])  # DRAFT
    res = api.approve_application(
        app["id"], {"decision_reason": "shouldn't work"},
        TEST_USERS["district_reviewer_headers"],
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_settle_already_rejected_transaction_returns_invalid_state(api):
    """PRD §3.6: "A `PENDING` transaction may instead be rejected by staff
    with a `rejection_reason` from the enumeration `ALLERGEN_CONFLICT`,
    `INELIGIBLE_STATE`, `INSUFFICIENT_FUNDS`, or `MANUAL`. Rejection sets
    `rejection_reason`, bumps the transaction's `version`, and produces no
    ledger movement. `REJECTED` is terminal."

    Design: Corner/state_machines/invalid_transition_settle_an_already_rejected_tx
    """
    set_clock("2026-06-02T09:00:00.000Z")
    hh = create_household(direct_certification_flag=True)
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-06-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    menu = create_menu_item(school_code="ELEM-101", list_price_cents=0)
    tx = create_service_transaction(stu["id"], menu["id"])
    reject_transaction(tx["id"], rejection_reason="MANUAL")
    # Now attempt to settle the REJECTED (terminal) transaction.
    res = api.settle_service_transaction(tx["id"], TEST_USERS["school_staff_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_withdraw_from_under_review_returns_invalid_state(api):
    """PRD §3.2: "A `DRAFT` or `SUBMITTED` application may be withdrawn by
    its owning parent, transitioning to `WITHDRAWN`. `WITHDRAWN` is
    terminal."

    Design: Corner/state_machines/invalid_transition_withdraw_from_under_review
    """
    setup_clean_world()
    hh = create_household()
    app = create_application(hh["id"])
    submit_application(app["id"], hh["id"])
    start_review(app["id"])
    # UNDER_REVIEW — withdraw is only valid from DRAFT or SUBMITTED.
    res = api.withdraw_application(app["id"], make_parent_headers(hh["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_clock_advance_past_valid_to_expires_active_eligibility(api):
    """PRD §3.4: "A separate non-revoke path retires a determination: when
    the server clock advances and an `ACTIVE` determination's
    `valid_to_utc` has been reached or passed, that determination
    transitions to `EXPIRED`."
    PRD §3.8: "The advance-and-expire capability is the clock-set capability
    plus an expiry sweep. The clock is advanced to the supplied
    `to_iso8601` instant, and then, in the same operation, every
    `EligibilityDetermination` with `lifecycle_status` of `ACTIVE` and
    `valid_to_utc` at or before the new clock instant is transitioned to
    `EXPIRED`."

    Design: Corner/state_machines/valid_transition_clock_advance_expires_eligibility
    """
    set_clock("2026-06-01T00:00:00.000Z")
    hh = create_household(direct_certification_flag=True)
    elig = create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-06-01T00:00:00.000Z",
        valid_to_utc="2026-06-30T00:00:00.000Z",
    )
    assert elig["lifecycle_status"] == "ACTIVE"
    advance_clock_and_expire("2026-07-01T00:00:00.000Z")
    res = api.get_eligibility_determination(
        elig["id"], TEST_USERS["usda_auditor_headers"]
    )
    data = validate_success(res, 200)
    assert data["lifecycle_status"] == "EXPIRED", (
        f"after advance_and_expire past valid_to_utc, lifecycle_status must be EXPIRED; "
        f"got {data['lifecycle_status']!r}"
    )
