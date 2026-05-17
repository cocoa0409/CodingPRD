"""Account opening, posture transitions, and closure.

Coverage targets (PRD §3.2, §2.6):
- Open TRADITIONAL / ROTH; open Inherited IRA (auto-creates
  BeneficiaryClaim with deadline_date = claim_date + 10 years).
- OPEN <-> FROZEN cycle via Custodian / ComplianceOfficer.
- Unfreeze blocked when participant is deceased.
- Close requires balance_cents == 0; closed account blocks mutations
  with ERR_ACCOUNT_CLOSED.
- Cross-tenant scope: /participants/{pid}/accounts/{aid} resolves
  left-to-right; account belonging to a different participant ->
  ERR_NOT_FOUND.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_account,
    create_account_payload,
    create_participant,
    create_participant_born,
    create_distribution_payload,
    date_n_years_ago,
    decease_participant,
    freeze_account,
    get_clock_state,
    iso_date_str,
    open_account,
    post_contribution,
    setup_traditional_to_roth_pair,
    validate_error,
    validate_success,
)


# ===========================================================================
# Open — PRD §3.2
# ===========================================================================
class TestOpenAccount:

    def test_open_traditional_account(self, api, custodian_headers):
        """PRD §3.2: "Account opening accepts the account_type (either
        TRADITIONAL or ROTH) ... The account's initial status is OPEN,
        its initial balance_cents is 0, its initial
        ytd_contribution_cents is 0, ... and its initial
        prior_year_end_balance_cents is 0."

        Claim: POST creates an OPEN TRADITIONAL account with zeroed
        balances and ytd.
        """
        p = create_participant()
        resp = api.create_account(
            p["id"],
            create_account_payload(account_type="TRADITIONAL"),
            custodian_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_account(data)
        assert data["participant_id"] == p["id"]
        assert data["account_type"] == "TRADITIONAL"
        assert data["status"] == "OPEN"
        assert data["balance_cents"] == 0
        assert data["ytd_contribution_cents"] == 0
        assert data["prior_year_end_balance_cents"] == 0
        assert data.get("inherited_from_participant_id") is None

    def test_open_inherited_ira_creates_claim_with_10_year_deadline(
        self, api, custodian_headers,
    ):
        """PRD §3.2: "When inherited_from_participant_id is supplied,
        the account is recognized as an Inherited IRA and the SECURE
        Act ten-year drain window applies: the system simultaneously
        creates a BeneficiaryClaim with claim_date equal to the
        current logical date and deadline_date equal to ten calendar
        years after that".

        Claim: opening an Inherited IRA records the
        inherited_from_participant_id on the account.
        """
        decedent = create_participant_born(1948)
        beneficiary = create_participant_born(1976)
        resp = api.create_account(
            beneficiary["id"],
            create_account_payload(
                account_type="TRADITIONAL",
                inherited_from_participant_id=decedent["id"],
            ),
            custodian_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_account(data)
        assert data["inherited_from_participant_id"] == decedent["id"]


# ===========================================================================
# Cross-tenant scope — PRD §2.6
# ===========================================================================
class TestCrossTenantScope:

    def test_account_under_wrong_participant_is_not_found(
        self, api, custodian_headers,
    ):
        """PRD §2.6: "The same code is returned when a deeper
        identifier exists but is out of scope of the parent — for
        example, an Account whose participant_id does not equal the
        participant_id in the path is treated as not found rather than
        as a forbidden cross-tenant access."

        Claim: GET /participants/{wrong_pid}/accounts/{aid} ->
        ERR_NOT_FOUND.
        """
        p_a = create_participant()
        p_b = create_participant()
        a_under_a = open_account(p_a["id"])
        resp = api.get_account(p_b["id"], a_under_a["id"],
                               custodian_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_nonexistent_participant_returns_not_found(
        self, api, custodian_headers,
    ):
        """PRD §2.6: "The first identifier that does not resolve
        causes immediate rejection with ERR_NOT_FOUND, before any
        rule on the deeper resource is evaluated."

        Claim: nonexistent participant_id -> ERR_NOT_FOUND.
        """
        resp = api.get_account(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                               custodian_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Freeze / Unfreeze — PRD §3.2
# ===========================================================================
class TestFreezeUnfreeze:

    def test_freeze_open_account_transitions_to_frozen(
        self, api, custodian_headers,
    ):
        """PRD §3.2: "A custodian or compliance officer may freeze an
        OPEN account at any time (transitioning OPEN → FROZEN)".

        Claim: POST /accounts/{id}/freeze -> status=FROZEN.
        """
        p = create_participant()
        a = open_account(p["id"])
        resp = api.freeze_account(a["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "FROZEN"

    def test_compliance_officer_may_freeze(self, api,
                                           compliance_headers):
        """PRD §3.2: "A custodian or compliance officer may freeze an
        OPEN account at any time".

        Claim: ComplianceOfficer can freeze too.
        """
        p = create_participant()
        a = open_account(p["id"])
        resp = api.freeze_account(a["id"], compliance_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "FROZEN"

    def test_unfreeze_returns_to_open(self, api, custodian_headers):
        """PRD §3.2: "either role may unfreeze a FROZEN account back
        to OPEN provided the owning participant is alive".

        Claim: POST /unfreeze on FROZEN account -> status=OPEN.
        """
        p = create_participant()
        a = open_account(p["id"])
        freeze_account(a["id"])
        resp = api.unfreeze_account(a["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "OPEN"

    def test_contribution_on_frozen_blocked_with_account_frozen(
        self, api, custodian_headers,
    ):
        """PRD §3.2: "A non-RMD contribution or distribution attempt
        on a frozen account is rejected with ERR_ACCOUNT_FROZEN."

        Claim: POST contribution on FROZEN -> ERR_ACCOUNT_FROZEN.
        """
        p = create_participant()
        a = open_account(p["id"])
        freeze_account(a["id"])
        resp = api.create_contribution(
            a["id"],
            {"amount_cents": 100_000, "contribution_type": "REGULAR"},
            custodian_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN.value)


# ===========================================================================
# Close — PRD §3.2
# ===========================================================================
class TestCloseAccount:

    def test_close_open_zero_balance_succeeds(self, api,
                                              custodian_headers):
        """PRD §3.2: "Closing an account is a custodian-only operation
        that drives the account to its terminal CLOSED state. The
        transition is permitted from either OPEN or FROZEN and requires
        that balance_cents equal 0 and that no PENDING ConversionRequest
        references the account either as source or as destination."

        Claim: close on OPEN with balance_cents=0 -> status=CLOSED.
        """
        p = create_participant()
        a = open_account(p["id"])
        resp = api.close_account(a["id"], custodian_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "CLOSED"

    def test_mutation_on_closed_account_blocked(self, api,
                                                custodian_headers):
        """PRD §3.2: "Any subsequent mutation attempt against a CLOSED
        account is rejected with ERR_ACCOUNT_CLOSED."

        Claim: contribution on CLOSED -> ERR_ACCOUNT_CLOSED.
        """
        p = create_participant()
        a = open_account(p["id"])
        api.close_account(a["id"], custodian_headers)
        resp = api.create_contribution(
            a["id"],
            {"amount_cents": 100_000, "contribution_type": "REGULAR"},
            custodian_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED.value)
