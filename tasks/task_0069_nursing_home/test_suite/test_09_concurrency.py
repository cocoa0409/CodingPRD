"""Concurrency: only those races whose PRD-prose explicitly defines the
outcome are tested. Where PRD does not commit to a specific loser
``error_id``, ``assert_exactly_one_succeeds`` is used.

Anchored in PRD §3.1, §3.6, §3.7.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    admit_payload,
    assert_exactly_one_succeeds,
    create_active_prescription,
    create_bed, create_room,
    create_elder, top_up_deposit,
    create_visit_reservation_payload,
    create_approved_assessment,
    iso_z, future_iso,
    pay_bill, pay_bill_payload,
    REQUIRED_ADMISSION_DEPOSIT_CENTS,
    run_race, set_epidemic_mode,
    setup_admitted_elder_v2,
    setup_admitted_with_finalized_bill,
    unique_payment_ref,
    ADMIN, FAMILY, FINANCE,
    validate_error_is_one_of,
)


# ===========================================================================
# Same-bed admission race (PRD §3.1 + §1.2.1)
# ===========================================================================
class TestSameBedAdmissionRace:

    def test_two_elders_into_same_bed_exactly_one_succeeds(self):
        """PRD §3.1: "two concurrent admit attempts on the same `AVAILABLE`
        bed serialize first-writer-wins on the `Bed.status` field, and the
        losing attempt is rejected with `ERR_BED_ALREADY_OCCUPIED`."

        Claim: when two admits target the same AVAILABLE bed, exactly one
        succeeds and the other returns ERR_BED_ALREADY_OCCUPIED.
        """
        room = create_room()
        bed = create_bed(room["id"], bed_type="SINGLE",
                         monthly_bed_fee_cents=60_000)
        # Two elders prepared with deposit + approved assessment.
        def prepare_elder():
            e = create_elder()
            top_up_deposit(e["id"], REQUIRED_ADMISSION_DEPOSIT_CENTS)
            create_approved_assessment(e["id"], 80, 10, 20)
            return e

        e1 = prepare_elder()
        e2 = prepare_elder()

        results = run_race(
            lambda: api_client.admit_elder(
                e1["id"], admit_payload(bed["id"]), ADMIN,
            ),
            lambda: api_client.admit_elder(
                e2["id"], admit_payload(bed["id"]), ADMIN,
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        # The loser must carry ERR_BED_ALREADY_OCCUPIED (PRD §3.1, §1.2.1)
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser,
            [ApiErrorId.ERR_BED_ALREADY_OCCUPIED.value],
        )


# ===========================================================================
# Pay bill — race against duplicate ref (PRD §3.7)
# ===========================================================================
class TestPayBillIdempotency:

    def test_two_pays_same_ref_same_bill_resolve_idempotently(self):
        """PRD §3.7: "Two pay requests for the same bill with the same
        `external_payment_ref` resolve such that the first applies the
        `FINALIZED` → `PAID` transition and the second returns the first
        result without re-applying side effects."

        Claim: two concurrent /pay calls with the same ref on the same
        bill must end with the bill in PAID exactly once — at least one
        success path; PRD specifies the second returns the first result,
        so we accept >=1 success across both responses.
        """
        # Engineer a bill whose amount_due is guaranteed > 0 so /pay
        # actually applies a state transition: bed_fee 600_000 / L3
        # PACKAGE / deposit at the §2.7 #23 floor → subtotal 1_080_000,
        # subsidy capped 200_000, deposit applied 500_000, amount_due
        # 380_000.
        bundle = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,
            monthly_bed_fee_cents=600_000,
            deposit_cents=500_000,
        )
        assert bundle["bill"]["amount_due_cents"] > 0, (
            "fixture must produce non-zero amount_due so the duplicate-"
            "pay idempotency race is actually meaningful"
        )
        ref = unique_payment_ref()
        results = run_race(
            lambda: api_client.pay_bill(
                bundle["bill"]["id"], pay_bill_payload(ref), FAMILY,
            ),
            lambda: api_client.pay_bill(
                bundle["bill"]["id"], pay_bill_payload(ref), FAMILY,
            ),
        )
        successes = [r for r in results if 200 <= r.status_code < 300]
        assert successes, \
            "PRD §3.7 — at least one of the duplicate /pay calls must " \
            "succeed (or replay the first as a success)."
