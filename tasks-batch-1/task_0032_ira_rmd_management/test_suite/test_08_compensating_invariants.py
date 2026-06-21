"""Compensating-action invariants: confirm-then-reverse conserves account
balances, ytd, and RMD-schedule satisfaction (PRD §3.3, §3.4, §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_owner,
    create_account,
    fund_account_with_contribution,
    create_pending_contribution,
    confirm_contribution,
    create_pending_distribution,
    confirm_distribution,
    create_rmd_schedule,
    get_account,
    get_rmd_schedule,
    make_account_owner_headers,
)


# =============================================================================
# Difficulty Rule 9 instance #1 — Contribution confirm + reverse conserves
# (cash, ytd, pretax_basis) triple
# =============================================================================


def test_contribution_confirm_then_reverse_conserves_account_balances(api):
    """PRD §3.3: "Upon a successful confirm the system stamps `confirmed_at`,
    advances the contribution's `status` to `CONFIRMED`, adds `amount_cents`
    to the account's `cash_balance_cents`, adds `amount_cents` to the
    account's `ytd_contribution_cents`, adds `amount_cents` to
    `pretax_basis_cents` if `contribution_kind` is `PRETAX` or to
    `aftertax_basis_cents` if it is `AFTERTAX` (Roth contributions touch
    neither pretax nor aftertax basis), appends an `AuditEvent` with
    `event_kind` `CONTRIBUTION_CONFIRMED` and `amount_cents` equal to the
    contribution amount, refreshes the account's `updated_at`, and increments
    the account's `version` by 1."
    PRD §3.3: "Reversal walks the same balance arithmetic in the opposite
    direction: `cash_balance_cents`, `ytd_contribution_cents`, and the
    relevant basis bucket each lose `amount_cents`; the contribution moves to
    `REVERSED`; `updated_at` is refreshed; `version` increments by 1."

    Design: Difficulty/compensating_invariant/contribution_confirm_then_reverse_conserves_account_balance_and_ytd
    """
    set_clock("2026-06-01T00:00:00Z")
    roger = create_owner(
        full_name="Roger",
        date_of_birth="1981-01-01",
        tax_id_last4="1818",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(roger["id"], "TRADITIONAL")
    pre_cash = trad["cash_balance_cents"]
    pre_ytd = trad["ytd_contribution_cents"]
    pre_pretax = trad["pretax_basis_cents"]
    v0 = trad["version"]

    pending = create_pending_contribution(
        account_id=trad["id"],
        owner_id=roger["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="PRETAX",
    )
    confirm_contribution(pending["id"], roger["id"], v0)

    # Mid-state: account has been mutated, balances reflect the confirm.
    mid_acct = get_account(trad["id"], make_account_owner_headers(roger["id"]))
    assert mid_acct["cash_balance_cents"] == pre_cash + 200_000
    assert mid_acct["ytd_contribution_cents"] == pre_ytd + 200_000

    # Reverse the contribution as PlanAdministrator.
    rev_res = api.reverse_contribution(
        pending["id"],
        {"expected_account_version": mid_acct["version"]},
        TEST_USERS["plan_admin_headers"],
    )
    reversed_data = validate_success(rev_res, expected_status=200)
    assert reversed_data["status"] == "REVERSED"

    # Post-state: invariants restored.
    post_acct = get_account(trad["id"], TEST_USERS["plan_admin_headers"])
    assert post_acct["cash_balance_cents"] == pre_cash, (
        f"cash_balance_cents must return to pre-confirm value (pre={pre_cash}, "
        f"post={post_acct['cash_balance_cents']})"
    )
    assert post_acct["ytd_contribution_cents"] == pre_ytd, (
        f"ytd_contribution_cents must return to pre-confirm value (pre={pre_ytd}, "
        f"post={post_acct['ytd_contribution_cents']})"
    )
    assert post_acct["pretax_basis_cents"] == pre_pretax, (
        f"pretax_basis_cents must return to pre-confirm value (pre={pre_pretax}, "
        f"post={post_acct['pretax_basis_cents']})"
    )


# =============================================================================
# Difficulty Rule 9 instance #2 — Distribution confirm + reverse conserves
# RMD-schedule satisfaction
# =============================================================================


def test_rmd_distribution_confirm_then_reverse_conserves_schedule_state(api):
    """PRD §3.4: "If `distribution_reason` is `RMD` the matching
    `RMDSchedule`'s `satisfied_amount_cents` increases by `amount_cents`; if
    the post-increase `satisfied_amount_cents` is greater than or equal to the
    schedule's `required_amount_cents`, the schedule transitions from `OPEN`
    to `SATISFIED`, or from `DELINQUENT` to `SATISFIED` if the confirm is a
    late cure."
    PRD §3.4: "Reversal moves the distribution to `REVERSED`, restores
    `cash_balance_cents` by `amount_cents`, voids the corresponding
    `Form1099R` by resetting its `gross_distribution_cents` to zero (the row
    remains in the audit record, but the gross is zeroed), reduces the
    matching `RMDSchedule`'s `satisfied_amount_cents` by `amount_cents` if
    `distribution_reason` was `RMD` (and reverts the schedule from `SATISFIED`
    back to `OPEN` if the reversal reopens a shortfall), recomputes
    `AccountOwner.rmd_posture`, refreshes the account's `updated_at`, and
    increments the account's `version` by 1."

    Design: Difficulty/compensating_invariant/distribution_confirm_then_reverse_conserves_rmd_satisfaction
    """
    set_clock("2026-06-01T00:00:00Z")
    sara = create_owner(
        full_name="Sara",
        date_of_birth="1953-03-03",
        tax_id_last4="1919",
        filing_status="SINGLE",
    )
    trad = create_account(sara["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=sara["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )
    sched = create_rmd_schedule(sara["id"], 2026)
    pre_satisfied = sched["satisfied_amount_cents"]
    pre_status = sched["status"]
    assert pre_satisfied == 0
    assert pre_status == "OPEN"

    required = sched["required_amount_cents"]
    assert required == 26_315

    refreshed_v1 = get_account(trad["id"], make_account_owner_headers(sara["id"]))
    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=sara["id"],
        amount_cents=required,
        distribution_reason="RMD",
        tax_year=2026,
    )
    confirm_distribution(pending["id"], sara["id"], refreshed_v1["version"])

    # Mid-state: schedule SATISFIED.
    mid_sched = get_rmd_schedule(sched["id"])
    assert mid_sched["status"] == "SATISFIED"
    assert mid_sched["satisfied_amount_cents"] == required

    # Reverse the distribution as PlanAdministrator.
    refreshed_v2 = get_account(trad["id"], TEST_USERS["plan_admin_headers"])
    rev_res = api.reverse_distribution(
        pending["id"],
        {"expected_account_version": refreshed_v2["version"]},
        TEST_USERS["plan_admin_headers"],
    )
    reversed_data = validate_success(rev_res, expected_status=200)
    assert reversed_data["status"] == "REVERSED"

    # Post-state: schedule reverts to OPEN with satisfied=0.
    post_sched = get_rmd_schedule(sched["id"])
    assert post_sched["satisfied_amount_cents"] == pre_satisfied, (
        f"RMDSchedule.satisfied_amount_cents must return to pre-confirm value "
        f"(pre={pre_satisfied}, post={post_sched['satisfied_amount_cents']})"
    )
    assert post_sched["status"] == pre_status, (
        f"RMDSchedule.status must revert to OPEN, got {post_sched['status']!r}"
    )
