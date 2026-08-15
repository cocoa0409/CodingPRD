"""Corner coverage — entity creation defaults, 404s, computed loan defaults,
watchlist entry rating floor, and charge-off ledger immutability.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, NON_EXISTENT_UUID,
    ApiErrorId,
    make_workout_officer_headers, make_loan_accounting_headers,
    make_borrower_with_loan, open_workout_case, make_borrower,
    create_borrower_payload, create_loan_payload, create_workout_case_payload,
    create_charge_off_payload,
    assert_borrower, assert_loan, assert_workout_case, assert_charge_off,
)
from test_helpers.api_client import api_client


def test_borrower_creation_defaults_and_system_fields(api):
    """PRD §3.1: "A `WorkoutOfficer` or `SystemAdmin` registers a borrower by
    supplying its `legal_name`, its `tax_id` (which must be unique across all
    borrowers), its industry classification `naics_code`, and the
    `internal_risk_rating` assigned at onboarding — an integer from 1, the best
    grade, to 10, the worst. When the credit is guaranteed, the registration also
    carries the `guarantor_name` and the guarantor's certified
    `guarantor_net_worth_cents`; when there is no guarantor, these default to an
    empty string and zero respectively. A new borrower's `status` is `ACTIVE`, and it
    stays `ACTIVE` until every workout case on every one of its loans has closed, at
    which point the system flips it to `EXITED` automatically — a reporting
    transition with no other side effects."
    PRD §2.4: "`version` (integer): starts at 1 at creation and increments by one on
    every mutation, including system-driven recomputations of derived fields."

    Design: Corner/entities/borrower_creation_defaults_and_system_fields
    """
    officer_h = make_workout_officer_headers("officer-b1")
    res = api_client.create_borrower(
        {"legal_name": "Solo Prop", "tax_id": "55-0000001", "naics_code": "541110",
         "internal_risk_rating": 5},
        officer_h)
    created = validate_success(res, 201)
    assert_borrower(created)
    assert created["status"] == "ACTIVE"
    assert created["guarantor_name"] == ""
    assert created["guarantor_net_worth_cents"] == 0
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])

    fetched = validate_success(api_client.get_borrower(created["id"], officer_h), 200)
    assert fetched["id"] == created["id"]
    assert fetched["status"] == "ACTIVE"


def test_borrower_not_found_returns_404(api):
    """PRD §2.7: "The first identifier that fails to resolve to an existing resource
    aborts the request with `ERR_NOT_FOUND` (HTTP 404), before any later segment or
    any business rule is examined."

    Design: Corner/entities/borrower_not_found_returns_404
    """
    officer_h = make_workout_officer_headers("officer-b2")
    res = api_client.get_borrower("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", officer_h)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_loan_creation_computed_defaults(api):
    """PRD §3.1: "At booking, `current_principal_cents` initializes to the full
    `original_principal_cents`, `charged_off_principal_cents` starts at zero, `is_tdr`
    and `nonaccrual` start false, and the loan's `status` is `PERFORMING`."

    Design: Corner/entities/loan_creation_computed_defaults
    """
    officer_h = make_workout_officer_headers("officer-b3")
    borrower = make_borrower(officer_h, legal_name="Default Check Co", tax_id="55-0000002",
                             naics_code="522110", internal_risk_rating=4)
    res = api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-D01",
         "original_principal_cents": 12345678, "contractual_rate_bps": 750,
         "days_past_due": 0},
        officer_h)
    loan = validate_success(res, 201)
    assert_loan(loan)
    assert loan["current_principal_cents"] == 12345678
    assert loan["charged_off_principal_cents"] == 0
    assert loan["is_tdr"] is False
    assert loan["nonaccrual"] is False
    assert loan["status"] == "PERFORMING"


def test_workout_case_entry_rating_downgrade_requires_rating_gte_6(api):
    """PRD §3.2: "When the trigger is `RISK_RATING_DOWNGRADE`, policy demands a
    genuinely deteriorated credit: `risk_rating_at_entry` must be at least 6, and a
    downgrade-triggered case opened at grade 5 or better is rejected with
    `ERR_REGULATORY_TIMING` (HTTP 422)."

    Design: Corner/entities/workout_case_entry_rating_downgrade_requires_rating_gte_6
    """
    officer_h = make_workout_officer_headers("officer-b4")
    borrower = make_borrower(officer_h, legal_name="Mild Risk LLC", tax_id="55-0000003",
                             naics_code="531310", internal_risk_rating=5)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-D02",
         "original_principal_cents": 10000000, "contractual_rate_bps": 700,
         "days_past_due": 10},
        officer_h))

    # Rating 5 with the downgrade trigger: rejected.
    res = api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "RISK_RATING_DOWNGRADE", "risk_rating_at_entry": 5,
         "case_officer_id": "officer-b4"},
        officer_h)
    validate_error(res, ApiErrorId.ERR_REGULATORY_TIMING.value, expected_status=422)

    # Rating 6 with the downgrade trigger: passes the floor.
    ok = validate_success(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "RISK_RATING_DOWNGRADE", "risk_rating_at_entry": 6,
         "case_officer_id": "officer-b4"},
        officer_h), 201)
    assert ok["status"] == "WATCHLIST"


def test_chargeoff_event_immutable_no_version(api):
    """PRD §2.4: "Three resources break this pattern because they are immutable
    ledger-style records once written: charge-off events, recovery events, and
    exit-strategy decisions. Each carries an `id` and a `created_at` — plus its own
    logical-clock booking stamp (`booked_at` on charge-off and recovery events,
    `decided_at` on exit decisions) — but neither `updated_at` nor `version` exists
    on them, because nothing about them ever changes after booking."
    PRD §3.8: "The system stamps `booked_at` from the logical clock, computes
    `is_partial` as true exactly when the amount is strictly less than the principal
    outstanding at booking, moves the amount out of `current_principal_cents` and
    into `charged_off_principal_cents`, and recomputes the case's
    loss-given-default."

    Design: Corner/entities/chargeoff_event_immutable_no_version
    """
    officer_h = make_workout_officer_headers("officer-i1")
    borrower = make_borrower(officer_h, legal_name="Ledger Immut Co", tax_id="55-0000004",
                             naics_code="541211", internal_risk_rating=8)
    loan = get_success_data(api_client.create_loan(
        {"borrower_id": borrower["id"], "loan_number": "LN-D03",
         "original_principal_cents": 9000000, "contractual_rate_bps": 800,
         "days_past_due": 65},
        officer_h))
    case = get_success_data(api_client.create_workout_case(
        loan["id"],
        {"entry_trigger": "DELINQUENCY_60", "risk_rating_at_entry": 8,
         "case_officer_id": "officer-i1"},
        officer_h))

    acct_h = make_loan_accounting_headers("acct-i1")
    res = api_client.create_charge_off(
        loan["id"], case["id"],
        create_charge_off_payload(amount_cents=1000000, reason_code="STATUTORY"),
        acct_h)
    event = validate_success(res, 201)
    assert_charge_off(event)
    assert event.get("booked_at"), "system must stamp booked_at from the logical clock"
    assert "version" not in event, "charge-off events are append-only: no version field"
    assert "updated_at" not in event, "charge-off events are append-only: no updated_at field"

    # The event is retrievable through the case's charge-off list.
    events, meta = validate_paginated(api_client.list_charge_offs(loan["id"], case["id"], acct_h))
    assert meta["total_count"] == 1
    assert events[0]["id"] == event["id"]
