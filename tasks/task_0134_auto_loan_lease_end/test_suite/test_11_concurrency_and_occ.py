"""Optimistic concurrency control and race-condition guarantees.

PRD §2.6 — OCC version field; ERR_VERSION_CONFLICT on mismatch.
PRD §2.11 — validation priority: state check (priority 4) precedes
the OCC check (priority 12).
PRD §3.5 / §3.7 / §3.9 — race-condition outcomes named in PRD prose.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    approve_loan_contract,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_customer,
    create_loan_contract,
    create_vehicle,
    list_payments_full,
    make_customer_headers,
    pay_payment,
    run_race,
    setup_active_loan,
    setup_lease_matured_with_assessment_issued,
    update_customer_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# OCC — version conflict on mutating endpoints
# ===========================================================================
class TestOccVersionConflict:

    def test_update_customer_with_stale_version_rejected(self, api):
        """PRD §2.6: "Every mutating endpoint that targets an entity
        with the common-fields set accepts an optional version value
        in the request body. When the field is present, the server
        compares it against the persisted entity's current version and
        rejects mismatches with ERR_VERSION_CONFLICT."

        Claim: PUT /customers/{id} with version one less than the
        persisted version -> ERR_VERSION_CONFLICT.
        """
        cust = create_customer(fico_score=700)
        # Bump the version by an update without version.
        resp = api_client.update_customer(
            cust["id"],
            update_customer_payload(full_name="Bumped"),
            TEST_USERS["platform_admin_headers"],
        )
        updated = validate_success(resp)
        stale = updated["version"] - 1
        resp = api_client.update_customer(
            cust["id"],
            update_customer_payload(
                full_name="Bumped Again", version=stale,
            ),
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_state_check_precedes_occ_check(self, api):
        """PRD §2.11: "a request with an out-of-date version against a
        contract that is already in the wrong state still returns the
        state error, not the version error, because the state check
        sits at priority four and the OCC check sits at priority
        twelve."

        Claim: approve an already-APPROVED loan with a stale version
        in the body -> ERR_LOAN_NOT_PENDING_APPROVAL (NOT
        ERR_VERSION_CONFLICT).
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle(msrp_cents=3_000_000)
        loan = create_loan_contract(
            cust, veh, down_payment_cents=200_000, term_months=36,
        )
        approve_loan_contract(cust, loan)
        # Send a stale version.
        resp = api_client.approve_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
            payload={"version": 0},
        )
        validate_error(
            resp, ApiErrorId.ERR_LOAN_NOT_PENDING_APPROVAL.value,
        )


# ===========================================================================
# Race — two pay attempts on the same payment
# ===========================================================================
class TestPaymentPayRace:

    def test_two_pay_attempts_exactly_one_wins(self, api):
        """PRD §3.5: "Two concurrent pay attempts on the same payment
        serialize on Payment.status: at most one of the transitions
        from SCHEDULED, LATE, or DEFAULTED to PAID succeeds, and the
        loser is rejected with ERR_PAYMENT_NOT_PAYABLE."

        Claim: two simultaneous /pay calls on the same SCHEDULED
        Payment — exactly one succeeds, the loser fails.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        advance_clock(cust, 30)
        rows = list_payments_full(cust, contract_id=loan["id"])
        rows.sort(key=lambda p: p["period_index"])
        p1 = rows[0]
        headers = make_customer_headers(cust["id"])
        results = run_race(
            lambda: api_client.pay_payment(cust["id"], p1["id"], headers),
            lambda: api_client.pay_payment(cust["id"], p1["id"], headers),
        )
        assert_exactly_one_succeeds(results[0], results[1])


# ===========================================================================
# Race — two lease-end elections on the same MATURED lease
# ===========================================================================
class TestLeaseEndRace:

    def test_two_lease_end_elections_exactly_one_wins(self, api):
        """PRD §3.9: "Two simultaneous lease-end elections on the same
        MATURED lease — for example, one caller submitting PURCHASE
        and another submitting RETURN — serialize on
        LeaseContract.status. Exactly one election succeeds; the
        loser sees the lease no longer in MATURED (it is in one of
        PURCHASED, RENEWED, or RETURNED) and is rejected with
        ERR_LEASE_NOT_MATURED."

        Claim: PURCHASE + RETURN race -> exactly one 2xx, the loser
        is 4xx (PRD names ERR_LEASE_NOT_MATURED for the loser).
        """
        cust, _, lease, _ = setup_lease_matured_with_assessment_issued(
            odometer_reading=36_000,
        )
        headers = make_customer_headers(cust["id"])
        results = run_race(
            lambda: api_client.submit_lease_end(
                cust["id"], lease["id"], {"election": "PURCHASE"},
                headers,
            ),
            lambda: api_client.submit_lease_end(
                cust["id"], lease["id"], {"election": "RETURN"},
                headers,
            ),
        )
        outcome = assert_race_outcome(list(results), 1, 1)
        # Loser must report ERR_LEASE_NOT_MATURED per PRD §3.9.
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == (
            ApiErrorId.ERR_LEASE_NOT_MATURED.value
        ), (
            f"loser must surface ERR_LEASE_NOT_MATURED; got "
            f"{body['data']['error_id']}"
        )


# ===========================================================================
# Race — two concurrent clock advances (OCC on Customer)
# ===========================================================================
class TestClockAdvanceRace:

    def test_two_clock_advances_serialize_via_occ(self, api):
        """PRD §2.6: "Two concurrent advances of the same customer's
        clock are an example of the OCC contract in action: the
        platform serializes them on the customer's version, so the
        first writer wins, the second receives ERR_VERSION_CONFLICT,
        and the loser is expected to refetch and retry — the clock
        never interleaves."

        Claim: two concurrent /clock/advance calls -> exactly one
        succeeds; the loser MUST surface ERR_VERSION_CONFLICT (PRD
        spells the error_id explicitly in §2.6).
        """
        cust = create_customer(fico_score=750)
        headers = TEST_USERS["platform_admin_headers"]
        results = run_race(
            lambda: api_client.advance_clock(
                cust["id"], {"days_advanced": 5}, headers,
            ),
            lambda: api_client.advance_clock(
                cust["id"], {"days_advanced": 5}, headers,
            ),
        )
        outcome = assert_race_outcome(list(results), 1, 1)
        loser = outcome["failures"][0]
        body = loser.json()
        assert body["data"]["error_id"] == (
            ApiErrorId.ERR_VERSION_CONFLICT.value
        ), (
            "loser must surface ERR_VERSION_CONFLICT per PRD §2.6; "
            f"got {body['data']['error_id']}"
        )
