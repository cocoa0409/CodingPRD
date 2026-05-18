"""Taxpayer registration and compliance lock/unlock workflows.

Coverage targets:
- POST /taxpayers — Taxpayer or IRSAdjudicator can register (PRD §3.1).
- New taxpayer starts in ACTIVE (PRD §3.1).
- Compliance lock transitions Taxpayer ACTIVE -> LOCKED (PRD §3.11).
- Compliance lock cancels all SCHEDULED EstimatedTaxPayments cascade
  (PRD §3.11).
- Compliance unlock transitions LOCKED -> ACTIVE (PRD §3.11).
- Locked taxpayer cannot perform mutations (PRD §3.11).
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    assert_taxpayer,
    compliance_lock,
    compliance_unlock,
    compute_tax_return,
    create_taxpayer,
    create_taxpayer_payload,
    iso_date,
    iso_instant_utc,
    make_taxpayer_headers,
    re_get_taxpayer,
    schedule_payment,
    setup_active_taxpayer_with_draft_return,
    setup_for_compliance_lock_cascade,
    validate_error,
    validate_success,
)


# ===========================================================================
# Registration — PRD §3.1
# ===========================================================================
class TestTaxpayerRegistration:

    def test_register_by_irs_adjudicator_succeeds(
        self, api, irs_adjudicator_headers,
    ):
        """PRD §3.1: "A taxpayer is brought into the system by a
        Taxpayer-role principal registering themselves, or by an
        IRSAdjudicator registering them on their behalf."

        Claim: IRSAdjudicator can POST /taxpayers and the response
        carries account_status ACTIVE.
        """
        payload = create_taxpayer_payload()
        resp = api.create_taxpayer(payload, irs_adjudicator_headers)
        data = validate_success(resp, expected_status=201)
        assert_taxpayer(data)
        assert data["account_status"] == "ACTIVE", (
            "PRD §3.1: 'Every newly registered taxpayer starts with "
            "an account_status of ACTIVE.'"
        )

    def test_registered_taxpayer_starts_active(self, api):
        """PRD §3.1: "Every newly registered taxpayer starts with an
        account_status of ACTIVE."

        Claim: GET /taxpayers/{id} on a freshly registered taxpayer
        reports account_status ACTIVE.
        """
        taxpayer = create_taxpayer()
        assert taxpayer["account_status"] == "ACTIVE"

    def test_default_is_blind_false(self, api, irs_adjudicator_headers):
        """PRD §3.1: "The boolean is_blind flag, which has financial
        consequences for the standard deduction, may be supplied at
        registration and otherwise defaults to false."

        Claim: omitting is_blind -> is_blind == false on the response.
        """
        payload = create_taxpayer_payload()
        payload.pop("is_blind", None)
        resp = api.create_taxpayer(payload, irs_adjudicator_headers)
        data = validate_success(resp, expected_status=201)
        assert data["is_blind"] is False


# ===========================================================================
# Compliance lock / unlock — PRD §3.11
# ===========================================================================
class TestComplianceLock:

    def test_lock_transitions_active_to_locked(
        self, api, irs_adjudicator_headers,
    ):
        """PRD §3.11: "The lock transitions the taxpayer's
        account_status from ACTIVE to LOCKED."

        Claim: POST /taxpayers/{id}/compliance-lock on an ACTIVE
        taxpayer changes account_status to LOCKED.
        """
        taxpayer = create_taxpayer()
        compliance_lock(taxpayer["id"])
        after = re_get_taxpayer(taxpayer["id"])
        assert after["account_status"] == "LOCKED"

    def test_unlock_transitions_locked_back_to_active(self, api):
        """PRD §3.11: "An adjudicator releases the lock by
        transitioning the taxpayer from LOCKED back to ACTIVE".

        Claim: a locked taxpayer becomes ACTIVE again after
        /compliance-unlock.
        """
        taxpayer = create_taxpayer()
        compliance_lock(taxpayer["id"])
        compliance_unlock(taxpayer["id"])
        after = re_get_taxpayer(taxpayer["id"])
        assert after["account_status"] == "ACTIVE"

    def test_lock_cancels_scheduled_estimated_payments(self, api):
        """PRD §3.11: "In the same operation the lock places, every
        EstimatedTaxPayment belonging to the taxpayer that is currently
        SCHEDULED is cascaded to CANCELLED with cancelled_at set to
        the current clock".

        Claim: SCHEDULED payments transition to CANCELLED with
        cancelled_at populated in the same operation as the lock.
        """
        (
            taxpayer, _tax_return, _w2, payment_q1, payment_q2,
        ) = setup_for_compliance_lock_cascade()
        compliance_lock(taxpayer["id"])

        # Re-read each payment.
        list_resp = api.list_estimated_payments(
            TEST_USERS["irs_adjudicator_headers"],
            params={"taxpayer_id": taxpayer["id"]},
        )
        data = list_resp.json()["data"]
        statuses = {row["id"]: row["status"] for row in data}
        assert statuses.get(payment_q1["id"]) == "CANCELLED"
        assert statuses.get(payment_q2["id"]) == "CANCELLED"
        # cancelled_at must be set.
        for row in data:
            if row["id"] in (payment_q1["id"], payment_q2["id"]):
                assert row.get("cancelled_at"), (
                    "PRD §3.11: 'cancelled_at set to the current clock "
                    "value'."
                )

    def test_locked_taxpayer_rejected_on_mutating_calls(self, api):
        """PRD §3.11: "While locked, every mutating endpoint operating
        on resources owned by that taxpayer ... is rejected with
        ERR_TAXPAYER_LOCKED."

        Claim: compute on a locked taxpayer's DRAFT return is
        rejected with ERR_TAXPAYER_LOCKED.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        compliance_lock(taxpayer["id"])
        resp = api.compute_tax_return(
            tax_return["id"], {}, make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_LOCKED.value)

    def test_locked_blocks_new_estimated_payment(self, api):
        """PRD §3.11: "While locked, every mutating endpoint operating
        on resources owned by that taxpayer — including creating or
        editing returns, importing documents, editing schedules,
        claiming or removing credits, scheduling new estimated
        payments, computing, e-filing, and submitting amendments — is
        rejected with ERR_TAXPAYER_LOCKED."

        Claim: POST /estimated-payments on a locked taxpayer ->
        ERR_TAXPAYER_LOCKED.
        """
        taxpayer = create_taxpayer()
        compliance_lock(taxpayer["id"])
        resp = api.create_estimated_payment(
            {
                "taxpayer_id": taxpayer["id"],
                "tax_year": 2025,
                "quarter": "Q1",
                "amount_cents": 10_000,
                "scheduled_pay_date": iso_date(date(2026, 12, 15)),
            },
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_LOCKED.value)
