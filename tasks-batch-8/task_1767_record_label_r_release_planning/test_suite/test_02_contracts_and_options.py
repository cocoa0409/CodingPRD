"""Contract lifecycle: option windows, termination, RBAC on finance endpoints."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_artist,
    create_draft_memo,
    create_label,
    get_recoupment_account,
    get_success_data,
    make_artist_portal_headers,
    sign_artist_via_memo,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import ADMIN, ANR, FIN, MKT, set_clock, sweep_label


# ===========================================================================
# Queue A — Difficulty/cross_entity_state_dependency/option_exercise_blocked_by_open_memo
# ===========================================================================


class TestOptionExerciseBlockedByOpenMemo:
    def test_exercise_blocked_then_unblocked(self):
        """PRD §3.3: "Exercise is allowed only while today is still on or before
        `current_term_end_date` — afterwards the window is shut and the attempt is
        rejected with `ERR_OPTION_WINDOW_CLOSED` — and only while no deal memo of
        the contract's artist is open in `DRAFT`, `PROPOSED`, `COUNTERED`, or
        `APPROVED`, because an open memo means renegotiation is in flight and the
        attempt is rejected with `ERR_RENEGOTIATION_IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/option_exercise_blocked_by_open_memo
        """
        label = create_label("Label X3")
        artist = create_artist(label["id"], "Artist X3")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, base_royalty_rate_bps=1_800,
            options_total=1, option_escalation_bps=150, term_months=12,
            valid_until_date="2028-06-01")
        # Advance to 2027-05-15: within the 90-day option window before 2027-08-01.
        set_clock("2027-05-15T00:00:00Z")
        sweep_label(label["id"])
        contract_now = get_success_data(api_client.get_contract(contract["id"], ADMIN))
        assert contract_now["status"] == "OPTION_WINDOW"

        # Draft a new renegotiation memo for the same artist (SIGNED is signable).
        memo2 = create_draft_memo(artist["id"], advance_cents=50_000,
                                  term_months=24, valid_until_date="2028-06-01")
        r = api_client.exercise_option(contract["id"], ADMIN)
        validate_error(r, ApiErrorId.ERR_RENEGOTIATION_IN_PROGRESS)
        after = get_success_data(api_client.get_contract(contract["id"], ADMIN))
        assert after["status"] == "OPTION_WINDOW"

        # Reject the open memo; exercise now succeeds.
        get_success_data(api_client.reject_deal_memo(memo2["id"], ANR))
        done = get_success_data(api_client.exercise_option(contract["id"], ADMIN))
        assert done["status"] == "EXTENDED"
        assert done["options_exercised"] == 1
        assert done["current_term_end_date"] == "2028-08-01"
        # effective = min(1800 + 1*150, 3000) = 1950
        assert done["effective_base_rate_bps"] == 1_950

    def test_exercise_recomputes_effective_rate(self):
        """PRD §3.3: "Exercising increments `options_exercised` by one, pushes
        `current_term_end_date` out by `option_term_months` calendar months,
        recomputes the contract's `effective_base_rate_bps` ... That effective rate
        is the lesser of two quantities — the `base_royalty_rate_bps` plus
        `options_exercised` times `option_escalation_bps`, and a hard ceiling of
        3,000 basis points".

        Design: Difficulty/cross_entity_state_dependency/option_exercise_blocked_by_open_memo
        """
        label = create_label("Label X3b")
        artist = create_artist(label["id"], "Artist X3b")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, base_royalty_rate_bps=1_800,
            options_total=1, option_escalation_bps=150, term_months=12,
            valid_until_date="2028-06-01")
        set_clock("2027-05-15T00:00:00Z")
        sweep_label(label["id"])
        done = get_success_data(api_client.exercise_option(contract["id"], ADMIN))
        assert done["effective_base_rate_bps"] == 1_950


# ===========================================================================
# Queue B — option/terminate validations
# ===========================================================================


class TestOptionWindowClosedRejected:
    def test_past_end_date_rejected(self):
        """PRD §3.3: "Exercise is allowed only while today is still on or before
        `current_term_end_date` — afterwards the window is shut and the attempt is
        rejected with `ERR_OPTION_WINDOW_CLOSED`".

        Design: Corner/validations/option_window_closed_rejected
        """
        label = create_label("Label Vb16")
        artist = create_artist(label["id"], "Artist Vb16")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, base_royalty_rate_bps=1_800,
            options_total=1, option_escalation_bps=150, term_months=12,
            valid_until_date="2028-06-01")
        set_clock("2027-05-15T00:00:00Z")
        sweep_label(label["id"])
        # Advance past current_term_end_date (2027-08-01) WITHOUT another sweep.
        set_clock("2027-08-02T00:00:00Z")
        r = api_client.exercise_option(contract["id"], ADMIN)
        validate_error(r, ApiErrorId.ERR_OPTION_WINDOW_CLOSED)
        # No further sweep has run, so status is unchanged.
        after = get_success_data(api_client.get_contract(contract["id"], ADMIN))
        assert after["status"] == "OPTION_WINDOW"


class TestUnrecoupedTerminateRequiresWriteoff:
    def test_terminate_false_then_true(self):
        """PRD §3.3: "When the recoupment account's `total_unrecouped_cents` is still
        positive, termination requires `write_off_unrecouped` to be true; refusing to
        write off a live balance is rejected with `ERR_UNRECOUPED_BALANCE`. When the
        write-off flag is set, the account's `writeoff_cents` is recorded as the full
        `total_unrecouped_cents` at that moment and all four bucket balances are
        zeroed."

        Design: Corner/validations/unrecouped_terminate_requires_writeoff
        """
        label = create_label("Label Vb17")
        artist = create_artist(label["id"], "Artist Vb17")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=100_000)
        get_success_data(api_client.disburse_advance(contract["id"], FIN))

        r = api_client.terminate_contract(contract["id"], {"write_off_unrecouped": False}, ADMIN)
        validate_error(r, ApiErrorId.ERR_UNRECOUPED_BALANCE)
        after = get_success_data(api_client.get_contract(contract["id"], ADMIN))
        assert after["status"] == "ACTIVE"

        done = get_success_data(api_client.terminate_contract(
            contract["id"], {"write_off_unrecouped": True}, ADMIN))
        assert done["status"] == "TERMINATED"
        account = get_recoupment_account(contract["id"])
        assert account["writeoff_cents"] == 100_000
        assert account["total_unrecouped_cents"] == 0
        assert account["recording_balance_cents"] == 0
        assert account["advance_balance_cents"] == 0
        assert account["tour_support_balance_cents"] == 0
        assert account["promo_balance_cents"] == 0


class TestContractSweep:
    def test_window_entry_then_expiry(self):
        """PRD §3.3: "When the sweep finds a contract in `ACTIVE` or `EXTENDED` whose
        today is on or after the date `option_window_days` before
        `current_term_end_date` and still on or before `current_term_end_date`, and
        whose `options_exercised` is still below `options_total`, it moves the
        contract to `OPTION_WINDOW` ... A contract whose `current_term_end_date` has
        passed moves to `EXPIRED` — from `ACTIVE`, `OPTION_WINDOW`, or `EXTENDED`
        alike — and appears in `expired_contract_ids`."

        Design: Corner/state_machines/contract_sweep_window_entry_and_expiry
        """
        label = create_label("Label S7")
        artist = create_artist(label["id"], "Artist S7")
        memo, contract = sign_artist_via_memo(
            artist["id"], advance_cents=0, base_royalty_rate_bps=1_800,
            options_total=1, option_escalation_bps=150, term_months=12,
            valid_until_date="2026-09-01")
        # First sweep: 2027-05-15 is within 90 days of end 2027-08-01 -> OPTION_WINDOW
        set_clock("2027-05-15T00:00:00Z")
        sweep1 = sweep_label(label["id"])
        assert contract["id"] in sweep1["window_entered_contract_ids"]
        after1 = get_success_data(api_client.get_contract(contract["id"], ADMIN))
        assert after1["status"] == "OPTION_WINDOW"

        # Second sweep past 2027-08-01 -> EXPIRED
        set_clock("2027-08-02T00:00:00Z")
        sweep2 = sweep_label(label["id"])
        assert contract["id"] in sweep2["expired_contract_ids"]
        after2 = get_success_data(api_client.get_contract(contract["id"], ADMIN))
        assert after2["status"] == "EXPIRED"


class TestDisburseRbac:
    def test_anr_cannot_disburse(self):
        """PRD §2.1: "A request whose role is not in the target endpoint's authorized
        role list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 table: `POST /api/contracts/{id}/disburse-advance` — FinanceController.

        Design: Corner/rbac/anr_cannot_disburse_advance
        """
        label = create_label("Label R2")
        artist = create_artist(label["id"], "Artist R2")
        memo, contract = sign_artist_via_memo(artist["id"], advance_cents=100_000)
        r = api_client.disburse_advance(contract["id"], ANR)
        validate_error(r, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        after = get_success_data(api_client.get_contract(contract["id"], ADMIN))
        assert after["advance_status"] == "PENDING"
