"""State-machine transitions for accounts, contributions, distributions, and RMD
schedules (PRD §3.2, §3.3, §3.4, §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
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
    advance_year_rollover,
    get_account,
    setup_funded_traditional_with_open_rmd,
    make_account_owner_headers,
)


# =============================================================================
# IRAAccount state machine — non-linear branching (Difficulty Rule 3 instance #1)
# =============================================================================


class TestIRAAccountFreezeUnfreezeLoop:
    """The IRAAccount state machine is non-linear: from ACTIVE it branches to
    FROZEN, CONVERSION_IN_PROGRESS, INHERITED, and CLOSED. The freeze/unfreeze
    pair is a revert loop — status returns to ACTIVE, only version advances."""

    def test_freeze_active_account_transitions_to_frozen(self, api):
        """PRD §3.2: "Freezing is a transition from `ACTIVE` to `FROZEN`; it is
        permitted only when no contribution against this account is in
        `PENDING` and no distribution against this account is in `PENDING`."
        PRD §2.7: "All transitions that mutate a row refresh its `updated_at`
        to the server's current clock and increment its `version` by exactly 1."

        Design: Difficulty/non_linear_state_machine/ira_account_branching_freeze_and_unfreeze_revert_loop
        """
        set_clock("2026-06-01T00:00:00Z")
        owner = create_owner(
            full_name="Eve", date_of_birth="1981-05-05", tax_id_last4="3333"
        )
        account = create_account(owner["id"], "TRADITIONAL")
        v0 = account["version"]

        freeze_res = api.freeze_account(
            account["id"],
            {"expected_account_version": v0},
            TEST_USERS["plan_admin_headers"],
        )
        frozen = validate_success(freeze_res, expected_status=200)
        assert frozen["status"] == "FROZEN", (
            f"freeze must move ACTIVE -> FROZEN, got {frozen['status']!r}"
        )
        assert frozen["version"] == v0 + 1, (
            f"version must increment by exactly 1, got {frozen['version']} (v0={v0})"
        )

    def test_unfreeze_frozen_account_returns_to_active(self, api):
        """PRD §3.2: "Unfreezing returns the account from `FROZEN` to `ACTIVE`
        and is permitted only if `deceased_at` on the owner is null."
        PRD §2.7: "All transitions that mutate a row refresh its `updated_at`
        to the server's current clock and increment its `version` by exactly 1."

        Design: Difficulty/non_linear_state_machine/ira_account_branching_freeze_and_unfreeze_revert_loop
        """
        set_clock("2026-06-01T00:00:00Z")
        owner = create_owner(
            full_name="Eve", date_of_birth="1981-05-05", tax_id_last4="3333"
        )
        account = create_account(owner["id"], "TRADITIONAL")
        v0 = account["version"]
        freeze_res = api.freeze_account(
            account["id"],
            {"expected_account_version": v0},
            TEST_USERS["plan_admin_headers"],
        )
        frozen = validate_success(freeze_res, expected_status=200)
        v1 = frozen["version"]

        unfreeze_res = api.unfreeze_account(
            account["id"],
            {"expected_account_version": v1},
            TEST_USERS["plan_admin_headers"],
        )
        unfrozen = validate_success(unfreeze_res, expected_status=200)
        assert unfrozen["status"] == "ACTIVE", (
            f"unfreeze must move FROZEN -> ACTIVE, got {unfrozen['status']!r}"
        )
        assert unfrozen["version"] == v1 + 1, (
            f"version must increment by exactly 1, got {unfrozen['version']} (v1={v1})"
        )


# =============================================================================
# RMDSchedule cyclic state machine — Difficulty Rule 3 instance #2
# =============================================================================


class TestRMDScheduleCyclicTransitions:
    """RMDSchedule has a cyclic shape: OPEN -> DELINQUENT (ops-run past deadline)
    -> SATISFIED (late cure via RMD-coded Distribution)."""

    def test_open_schedule_transitions_to_delinquent_on_year_rollover(self, api):
        """PRD §3.7: "A `PlanAdministrator` runs the year-rollover capability
        when the calendar year turns. The capability takes a `new_tax_year`
        value, advances every account's `tax_year_marker` to that value, resets
        every account's `ytd_contribution_cents` to zero, then sweeps every
        `OPEN` `RMDSchedule` and transitions to `DELINQUENT` any schedule whose
        `deadline_at` has been passed by the current `SystemClock.current_utc`
        and whose `satisfied_amount_cents` remains strictly below its
        `required_amount_cents`."

        Design: Difficulty/non_linear_state_machine/rmd_schedule_cyclic_open_delinquent_satisfied_loop
        """
        # DOB 1951-02-10 makes the owner age 75 at EOY 2026 (NOT the first RMD
        # year), so per PRD §3.7 the schedule's deadline_at is December 31 of
        # the tax_year, which the 2027-01-15 clock below passes. A first-RMD
        # year (age 73) would push deadline_at to April 1 of tax_year+1, which
        # 2027-01-15 would NOT pass.
        owner, account, schedule = setup_funded_traditional_with_open_rmd(
            iso8601="2026-06-01T00:00:00Z",
            date_of_birth="1951-02-10",
            cash_cents=700_000,
            tax_year=2026,
        )
        assert schedule["status"] == "OPEN", (
            f"expected new schedule OPEN, got {schedule['status']!r}"
        )

        # Advance the clock past the 2026-12-31 deadline.
        set_clock("2027-01-15T00:00:00Z")
        advance_year_rollover(2027)

        from test_helpers import get_rmd_schedule

        after = get_rmd_schedule(schedule["id"])
        assert after["status"] == "DELINQUENT", (
            f"unsatisfied OPEN schedule past deadline must flip to DELINQUENT, "
            f"got {after['status']!r}"
        )

    def test_late_cure_rmd_distribution_returns_delinquent_to_satisfied(self, api):
        """PRD §3.7: "A late cure is permitted: confirming an `RMD`-coded
        distribution against a `DELINQUENT` schedule pulls the schedule back
        to `SATISFIED` once `satisfied_amount_cents` reaches
        `required_amount_cents`, and `rmd_posture` is recomputed accordingly."

        Design: Difficulty/non_linear_state_machine/rmd_schedule_cyclic_open_delinquent_satisfied_loop
        """
        # DOB 1951-02-10 makes the owner age 75 at EOY 2026 (NOT the first RMD
        # year), so per PRD §3.7 the schedule's deadline_at is December 31 of
        # the tax_year, which the 2027-01-15 clock below passes — letting the
        # OPEN -> DELINQUENT sweep fire so the late cure can be exercised.
        owner, account, schedule = setup_funded_traditional_with_open_rmd(
            iso8601="2026-06-01T00:00:00Z",
            date_of_birth="1951-02-10",
            cash_cents=700_000,
            tax_year=2026,
        )
        required = schedule["required_amount_cents"]
        assert required > 0, "fixture must produce a positive RMD requirement"

        # Push the schedule to DELINQUENT via ops-run year-rollover.
        set_clock("2027-01-15T00:00:00Z")
        advance_year_rollover(2027)

        from test_helpers import get_rmd_schedule

        delinq = get_rmd_schedule(schedule["id"])
        assert delinq["status"] == "DELINQUENT"

        # Late cure: confirm an RMD-coded distribution satisfying the required amount.
        refreshed = get_account(account["id"], make_account_owner_headers(owner["id"]))
        pending = create_pending_distribution(
            account_id=account["id"],
            owner_id=owner["id"],
            amount_cents=required,
            distribution_reason="RMD",
            tax_year=2026,
        )
        confirm_distribution(pending["id"], owner["id"], refreshed["version"])

        cured = get_rmd_schedule(schedule["id"])
        assert cured["status"] == "SATISFIED", (
            f"late cure must move DELINQUENT -> SATISFIED, got {cured['status']!r}"
        )
        assert cured["satisfied_amount_cents"] == required, (
            f"satisfied_amount_cents must equal required after cure, "
            f"got {cured['satisfied_amount_cents']} (required={required})"
        )


# =============================================================================
# Corner: contribution reject / idempotency / closed-account terminal
# =============================================================================


def test_reject_pending_contribution_terminates_no_balance_change(api):
    """PRD §3.3: "A `PlanAdministrator` may reject a `PENDING` contribution at
    any time before confirm; the contribution moves to `REJECTED` and no
    balances change."

    Design: Corner/state_machines/contribution_reject_from_pending_terminates_no_balance_change
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="Aaron", date_of_birth="1980-01-01", tax_id_last4="1111"
    )
    account = create_account(owner["id"], "TRADITIONAL")
    pre_cash = account["cash_balance_cents"]
    contribution = create_pending_contribution(
        account_id=account["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )

    rej_res = api.reject_contribution(
        contribution["id"], TEST_USERS["plan_admin_headers"]
    )
    rejected = validate_success(rej_res, expected_status=200)
    assert rejected["status"] == "REJECTED", (
        f"reject must move PENDING -> REJECTED, got {rejected['status']!r}"
    )

    post_acct = get_account(account["id"], TEST_USERS["plan_admin_headers"])
    assert post_acct["cash_balance_cents"] == pre_cash, (
        f"reject must not change cash_balance_cents (pre={pre_cash}, "
        f"post={post_acct['cash_balance_cents']})"
    )


def test_close_active_account_with_nonzero_balance_rejected(api):
    """PRD §3.2: "An `AccountOwner` may close their own `ACTIVE` account only
    when `cash_balance_cents` is zero, when their own `deceased_at` is null,
    and when no `RMDSchedule` for this owner against this Traditional account
    is in `OPEN`; the transition runs from `ACTIVE` to `CLOSED`."
    PRD §2.6: "Third, state: for action endpoints the target entity must be in
    the from-state declared by the relevant transition, with rejection code
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/ira_account_close_active_with_nonzero_balance_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="Aaron",
        date_of_birth="1980-01-01",
        tax_id_last4="1111",
        modified_agi_cents=5_000_000,
    )
    account = create_account(owner["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=account["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )
    refreshed = get_account(account["id"], TEST_USERS["plan_admin_headers"])
    assert refreshed["cash_balance_cents"] > 0

    res = api.close_account(
        account["id"],
        {"expected_account_version": refreshed["version"]},
        TEST_USERS["plan_admin_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_double_confirm_contribution_rejected_invalid_state(api):
    """PRD §2.6: "Third, state: for action endpoints the target entity must be
    in the from-state declared by the relevant transition, with rejection code
    `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "The contribution lands in `PENDING` and persists in that state
    until either a `PlanAdministrator` rejects it (moving it to `REJECTED`) or
    the owner confirms it (moving it to `CONFIRMED`)."

    Design: Corner/state_machines/contribution_idempotency_double_confirm_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="Aaron",
        date_of_birth="1980-01-01",
        tax_id_last4="1111",
        modified_agi_cents=5_000_000,
    )
    account = create_account(owner["id"], "TRADITIONAL")
    pending = create_pending_contribution(
        account_id=account["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )
    confirm_contribution(pending["id"], owner["id"], account["version"])

    # Second confirm: status is no longer PENDING.
    refreshed = get_account(account["id"], make_account_owner_headers(owner["id"]))
    res = api.confirm_contribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(owner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_closed_account_rejects_further_freeze_attempts(api):
    """PRD §3.2: "`CLOSED` is terminal."
    PRD §2.6: "Third, state: for action endpoints the target entity must be in
    the from-state declared by the relevant transition, with rejection code
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/closed_account_terminal_no_further_transitions
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="Aaron", date_of_birth="1980-01-01", tax_id_last4="1111"
    )
    account = create_account(owner["id"], "TRADITIONAL")
    v0 = account["version"]

    close_res = api.close_account(
        account["id"],
        {"expected_account_version": v0},
        TEST_USERS["plan_admin_headers"],
    )
    closed = validate_success(close_res, expected_status=200)
    assert closed["status"] == "CLOSED"
    v1 = closed["version"]

    # Any further state-changing call must fail with ERR_INVALID_STATE.
    res = api.freeze_account(
        account["id"],
        {"expected_account_version": v1},
        TEST_USERS["plan_admin_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
