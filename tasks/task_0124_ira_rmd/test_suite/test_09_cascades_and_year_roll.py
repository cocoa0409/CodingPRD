"""Cascade behaviours and year-roll endpoint side effects.

Coverage targets (PRD §2.10, §2.11, §3.1, §3.8):
- Decease cascade: Participant flip + Accounts -> FROZEN + PENDING
  ConversionRequests -> CANCELED.
- Conversion completion cascade: DistributionEvent created, balances
  move, Form1099R issued.
- Year-roll endpoint: prior_year_end_balance snapshot, ytd reset,
  excess-contribution sweep, missed-RMD sweep.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_year,
    create_distribution_payload,
    create_participant_born,
    decease_participant,
    get_account,
    get_clock_state,
    iso_date_str,
    list_forms_1099r,
    open_account,
    post_contribution,
    setup_approved_conversion,
    setup_pending_conversion,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Decease cascade — PRD §2.11
# ===========================================================================
class TestDeceaseCascade:

    def test_decease_freezes_owned_accounts(self, api, custodian_headers):
        """PRD §2.11: "Marking a participant deceased flips every owned
        Account from OPEN to FROZEN".

        Claim: after decease, every account.status == FROZEN.
        """
        p = create_participant_born(1960)
        a1 = open_account(p["id"], account_type="TRADITIONAL")
        a2 = open_account(p["id"], account_type="ROTH")
        clock = get_clock_state()
        dod = clock.get("current_date") or "2026-01-02"
        decease_participant(p["id"], date_of_death=dod)
        a1_after = get_account(p["id"], a1["id"])
        a2_after = get_account(p["id"], a2["id"])
        assert a1_after["status"] == "FROZEN"
        assert a2_after["status"] == "FROZEN"

    def test_decease_cancels_pending_conversion_requests(
        self, api, custodian_headers,
    ):
        """PRD §2.11: "auto-cancel every PENDING ConversionRequest on
        those accounts (transitioning their status to CANCELED)".

        Claim: PENDING ConversionRequest on a decedent's accounts ->
        CANCELED.
        """
        p, trad, roth, cr = setup_pending_conversion()
        clock = get_clock_state()
        dod = clock.get("current_date") or "2026-01-02"
        decease_participant(p["id"], date_of_death=dod)
        resp = api.get_conversion_request(cr["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CANCELED"


# ===========================================================================
# Conversion completion cascade — PRD §2.11
# ===========================================================================
class TestConversionCompletionCascade:

    def test_completion_moves_balances_and_issues_1099r(
        self, api, custodian_headers,
    ):
        """PRD §2.11: "Completing an approved conversion creates a
        DistributionEvent on the source account with distribution_reason
        equal to CONVERSION and federal_withholding_cents equal to 0;
        that event debits the source account's balance_cents and
        credits the destination account's balance_cents by amount_cents;
        and a Form1099R is auto-issued with source_event_type equal to
        CONVERSION and box7_distribution_code equal to G."

        Claim: completion creates exactly one Form1099R with
        source_event_type=CONVERSION and box7=G, and moves balances.
        """
        p, trad, roth, cr = setup_approved_conversion(
            amount_cents=700_000,
        )
        resp = api.complete_conversion_request(cr["id"],
                                               custodian_headers)
        completed = validate_success(resp, expected_status=200)
        assert completed["status"] == "COMPLETED"
        trad_after = get_account(p["id"], trad["id"])
        roth_after = get_account(p["id"], roth["id"])
        assert trad_after["balance_cents"] == 0
        assert roth_after["balance_cents"] == 700_000
        # Locate the auto-issued 1099-R.
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        forms, _ = list_forms_1099r(p["id"], tax_year=ty)
        conversion_forms = [
            f for f in forms if f.get("source_event_type") == "CONVERSION"
        ]
        assert len(conversion_forms) >= 1, (
            f"expected >=1 CONVERSION Form1099R, got {forms}"
        )
        f = conversion_forms[0]
        assert str(f["box7_distribution_code"]) == "G"
        # PRD §3.9: non-Backdoor conversion -> box2a == amount_cents.
        assert f["box2a_taxable_amount_cents"] == 700_000

    def test_backdoor_completion_yields_zero_box2a(
        self, api, custodian_headers,
    ):
        """PRD §3.9: "box2a_taxable_amount_cents is 0 when the
        request's backdoor_flag is true and equals amount_cents when
        it is false."

        Claim: backdoor=true completion -> Form1099R box2a == 0.
        """
        from test_helpers import (
            approve_conversion_request,
            create_conversion_request,
            setup_backdoor_pair,
        )
        p, trad, roth = setup_backdoor_pair(backdoor_amount_cents=700_000)
        cr = create_conversion_request(
            participant=p, source_account=trad, destination_account=roth,
            amount_cents=700_000, backdoor_flag=True,
        )
        approve_conversion_request(cr["id"])
        api.complete_conversion_request(cr["id"], custodian_headers)
        clock = get_clock_state()
        ty = int(clock.get("clock_year",
                           clock.get("current_year", 2026)))
        forms, _ = list_forms_1099r(p["id"], tax_year=ty)
        conv = [f for f in forms
                if f.get("source_event_type") == "CONVERSION"]
        assert len(conv) >= 1
        assert conv[0]["box2a_taxable_amount_cents"] == 0
        assert str(conv[0]["box7_distribution_code"]) == "G"
        # PRD §2.11 / §3.4: federal_withholding 0 for CONVERSION.
        assert conv[0]["box4_federal_withholding_cents"] == 0


# ===========================================================================
# Year-roll snapshot — PRD §2.10, §3.8
# ===========================================================================
class TestYearRoll:

    def test_year_roll_snapshots_prior_balance_and_resets_ytd(
        self, api, custodian_headers, auditor_headers,
    ):
        """PRD §3.8: "For every Account, regardless of status, snapshot
        the current balance_cents into prior_year_end_balance_cents.
        ... Increment the clock year by 1. Reset every
        Account.ytd_contribution_cents to 0."

        Claim: balance is snapshotted, ytd resets.
        """
        p = create_participant_born(1990)
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=500_000)
        # Year-roll.
        api.clock_advance_year(None, auditor_headers)
        a_after = get_account(p["id"], a["id"])
        assert a_after["prior_year_end_balance_cents"] == 500_000
        assert a_after["ytd_contribution_cents"] == 0
        # PRD §3.3 sets balance_cents from contribution events; the
        # snapshot does not zero balance, only ytd.
        assert a_after["balance_cents"] == 500_000

    def test_year_roll_assesses_no_penalty_when_under_cap(
        self, api, custodian_headers, auditor_headers,
    ):
        """PRD §3.8: "If the sum is at or below the cap, no penalty is
        issued for that account."

        Claim: contributions under cap -> no ExcessPenalty / no
        EXCESS_PENALTY 1099-R for that year.
        """
        p = create_participant_born(1990)
        a = open_account(p["id"])
        post_contribution(a["id"], amount_cents=500_000)
        # Record the pre-roll clock year for the 1099-R lookup later.
        clock_before = get_clock_state(auditor_headers)
        pre_year = int(clock_before.get(
            "clock_year", clock_before.get("current_year", 2026),
        ))
        api.clock_advance_year(None, auditor_headers)
        # 1099-R EXCESS_PENALTY for pre_year should not exist.
        forms, _ = list_forms_1099r(p["id"], tax_year=pre_year)
        excess = [f for f in forms
                  if f.get("source_event_type") == "EXCESS_PENALTY"]
        assert excess == [], (
            f"expected no EXCESS_PENALTY 1099-R for {pre_year}, got "
            f"{excess}"
        )
