"""CSED tolling mechanics: provisional vs final, half-open interval
arithmetic, expiration cascade. PRD §3.3.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    create_taxpayer,
    create_tax_liability,
    decide_oic,
    get_tax_liability,
    iso_instant_utc,
    parse_iso,
    run_sweep,
    setup_provisional_csed_after_oic_submit,
    take_up_oic,
    withdraw_oic,
)


class TestProvisionalVsFinalCSED:

    def test_open_tolling_drift_then_freeze_after_oic_reject(self):
        """PRD §3.3: "While at least one tolling event remains open,
        the effective expiration drifts forward as wall-clock time
        advances; once every tolling event has been closed, the
        effective expiration is fixed and no longer drifts unless a new
        tolling event opens."
        PRD §3.3: "the total tolling duration is the sum of the lengths
        of the merged intervals (in seconds, ISO 8601 UTC). The
        effective expiration is csed_base_date advanced by that total
        tolling duration."

        Claim: with an OPEN tolling event, csed_effective_date
        immediately reflects the wall-clock interval (T1-T0) of drift;
        after the OIC is decided/rejected (closing the event),
        csed_effective_date freezes at csed_base + (T1-T0) and stays
        there even as the clock advances 30 more days.

        # difficulty: dual_variant_calc/csed_provisional_vs_final
        """
        t0_iso = "2020-01-01T00:00:00.000Z"
        t1_iso = "2020-04-01T00:00:00.000Z"
        taxpayer, liability, oic = setup_provisional_csed_after_oic_submit(
            base_clock=t0_iso,
            mdi_cents=200_000,
            liability_amount_cents=1_000_000,
            offer_amount_cents=1_500_000,
            schedule_months=5,
            deposit_cents=300_000,
        )
        # Advance to T1 while the OIC_PENDING tolling event is open.
        advance_clock_to(t1_iso)
        provisional = get_tax_liability(liability["id"])
        csed_base = parse_iso(provisional["csed_base_date"])
        drift = parse_iso(t1_iso) - parse_iso(t0_iso)
        expected_provisional = csed_base + drift
        assert parse_iso(provisional["csed_effective_date"]) == expected_provisional, (
            "while OIC_PENDING is open, csed_effective_date drifts to "
            f"csed_base + (T1-T0) = {expected_provisional.isoformat()}"
        )
        # Officer A takes up; Officer B rejects, closing the tolling
        # event at T1.
        take_up_oic(oic["id"], officer_id="csed-officer-A")
        decide_oic(oic["id"], "REJECT", officer_id="csed-officer-B")
        # Now the closed-interval sum is exactly (T1 - T0) seconds.
        final = get_tax_liability(liability["id"])
        expected_final = csed_base + drift
        assert parse_iso(final["csed_effective_date"]) == expected_final, (
            "after the OIC_PENDING tolling closes, csed_effective_date "
            f"freezes at csed_base + (T1-T0) = {expected_final.isoformat()}"
        )
        # Advance another 30 days — final value must not drift.
        advance_clock_to("2020-05-01T00:00:00.000Z")
        still_final = get_tax_liability(liability["id"])
        assert parse_iso(still_final["csed_effective_date"]) == expected_final, (
            "PRD §3.3: 'once every tolling event has been closed, the "
            "effective expiration is fixed and no longer drifts unless "
            "a new tolling event opens.'"
        )

    def test_zero_length_tolling_does_not_advance_csed(self):
        """PRD §3.3: "the total tolling duration is the sum of the
        lengths of the merged intervals (in seconds, ISO 8601 UTC). The
        effective expiration is csed_base_date advanced by that total
        tolling duration."

        Claim: opening and immediately closing an OIC_PENDING tolling
        at the same instant leaves csed_effective_date == csed_base_date.

        # difficulty: compensating_invariant/csed_tolling_balance_invariant
        """
        from test_helpers import (
            advance_clock_to,
            create_draft_oic,
            create_taxpayer,
            create_tax_liability,
            make_taxpayer_headers,
            pay_oic_deposit,
            submit_oic,
        )
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_000_000,
        )
        pre_value = parse_iso(
            get_tax_liability(liability["id"])["csed_effective_date"]
        )
        # Open AND close the tolling at the same instant: 2021-06-15.
        advance_clock_to("2021-06-15T00:00:00.000Z")
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic["id"], 300_000)
        submit_oic(taxpayer["id"], oic["id"])
        # Withdraw immediately (same instant) — opens AND closes the
        # OIC_PENDING tolling at 2021-06-15.
        withdraw_oic(taxpayer["id"], oic["id"])
        post_value = parse_iso(
            get_tax_liability(liability["id"])["csed_effective_date"]
        )
        assert post_value == pre_value, (
            "PRD §3.3: zero-length tolling interval contributes zero "
            "seconds, so csed_effective_date is unchanged"
        )


class TestCSEDExpirationCascade:

    def test_csed_expiration_zeros_balance_and_transitions_to_expired(self):
        """PRD §3.3: "When the server clock reaches or exceeds a
        liability's csed_effective_date and the liability's status is
        OPEN or CNC, the next sweep transitions the liability to
        EXPIRED, writes off the balance by setting current_balance_cents
        to zero."

        Claim: clock advances past csed_effective_date + sweep moves the
        liability to EXPIRED with current_balance_cents == 0.
        """
        advance_clock_to("2020-01-01T00:00:00.000Z")
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"],
            assessment_date="2020-01-01T00:00:00.000Z",
            original_assessed_amount_cents=1_000_000,
        )
        # Advance well past csed_base_date (2030-01-01).
        advance_clock_to("2030-06-01T00:00:00.000Z")
        run_sweep()
        refreshed = get_tax_liability(liability["id"])
        assert refreshed["status"] == "EXPIRED"
        assert refreshed["current_balance_cents"] == 0, (
            "PRD §3.3: 'writes off the balance by setting "
            "current_balance_cents to zero'"
        )
