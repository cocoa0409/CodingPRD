"""Contribution headroom, annual/ATW caps, validation priority, OCC, and reversal.

Difficulty (queue A) instances appear with >=2 tests each; corner (queue B)
instances appear once. Each docstring ends with its Design tag.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_contribution_payload,
    make_program_admin_headers,
    make_beneficiary_headers,
    setup_open_account,
    post_contribution,
    get_account,
)

ADMIN = make_program_admin_headers()


# ===========================================================================
# Difficulty: combinatorial_formula / contribution_headroom_atw_nested_min_branch
# ===========================================================================
def test_atw_contribution_over_min_fpl_income_cap_rejected(api):
    """PRD 3.6: "The ABLE-to-Work ceiling is the smaller of the program's
    `able_to_work_fpl_cents` and the beneficiary's `gross_employment_income_ytd_cents`, and
    the room remaining is that ceiling minus the account's `atw_contrib_ytd_cents`; if
    `amount_cents` exceeds that room, the contribution is rejected with `ERR_ATW_CAP_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/contribution_headroom_atw_nested_min_branch
    """
    _, _, beneficiary, account = setup_open_account(
        beneficiary_overrides={
            "gross_employment_income_ytd_cents": 1_200_000,
            "employer_retirement_plan_participant": False,
        }
    )
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    # atw cap = min(1_506_000, 1_200_000) = 1_200_000; prior ATW of 1_150_000 leaves room 50_000.
    post_contribution(
        account["id"], 1_150_000, account["version"],
        headers=ben_headers, contribution_type="ABLE_TO_WORK",
    )
    current_version = get_account(account["id"])["version"]
    resp = api.create_contribution(
        account["id"],
        create_contribution_payload(60_000, current_version, contribution_type="ABLE_TO_WORK"),
        ben_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ATW_CAP_EXCEEDED.value, 409)


def test_atw_over_cap_rejection_leaves_ytd_unchanged(api):
    """PRD 3.6: "A contribution that fails any of these checks returns an error and is not
    persisted — there is no rejected contribution state."

    Design: Difficulty/combinatorial_formula/contribution_headroom_atw_nested_min_branch
    """
    _, _, beneficiary, account = setup_open_account(
        beneficiary_overrides={
            "gross_employment_income_ytd_cents": 1_200_000,
            "employer_retirement_plan_participant": False,
        }
    )
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    first = post_contribution(
        account["id"], 1_150_000, account["version"],
        headers=ben_headers, contribution_type="ABLE_TO_WORK",
    )
    api.create_contribution(
        account["id"],
        create_contribution_payload(60_000, first["version"], contribution_type="ABLE_TO_WORK"),
        ben_headers,
    )
    after = get_account(account["id"])
    assert after["atw_contrib_ytd_cents"] == 1_150_000, (
        f"a rejected ATW contribution must not change atw_contrib_ytd_cents, "
        f"got {after['atw_contrib_ytd_cents']}"
    )


# ===========================================================================
# Difficulty: boundary_precision_check / annual_cap_boundary_exact_vs_plus_one_cent
# ===========================================================================
def test_contribution_to_exactly_annual_cap_succeeds(api):
    """PRD 3.6: "For a `REGULAR` or `ROLLOVER_529` contribution, the room remaining under the
    annual cap is the program's `annual_contribution_cap_cents` minus the account's
    `regular_contrib_ytd_cents`; if `amount_cents` exceeds that room, the contribution is
    rejected with `ERR_ANNUAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/annual_cap_boundary_exact_vs_plus_one_cent
    """
    _, _, beneficiary, account = setup_open_account()
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    post_contribution(account["id"], 1_800_000, account["version"], headers=ben_headers)
    current_version = get_account(account["id"])["version"]
    # room = 1_900_000 - 1_800_000 = 100_000; a 100_000 contribution is exactly at the cap.
    resp = api.create_contribution(
        account["id"], create_contribution_payload(100_000, current_version), ben_headers
    )
    validate_success(resp, 201)
    after = get_account(account["id"])
    assert after["regular_contrib_ytd_cents"] == 1_900_000, (
        f"ytd must reach exactly the cap, got {after['regular_contrib_ytd_cents']}"
    )


def test_contribution_one_cent_over_annual_cap_rejected(api):
    """PRD 3.6: "For a `REGULAR` or `ROLLOVER_529` contribution, the room remaining under the
    annual cap is the program's `annual_contribution_cap_cents` minus the account's
    `regular_contrib_ytd_cents`; if `amount_cents` exceeds that room, the contribution is
    rejected with `ERR_ANNUAL_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/annual_cap_boundary_exact_vs_plus_one_cent
    """
    _, _, beneficiary, account = setup_open_account()
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    post_contribution(account["id"], 1_800_000, account["version"], headers=ben_headers)
    v2 = get_account(account["id"])["version"]
    post_contribution(account["id"], 100_000, v2, headers=ben_headers)
    v3 = get_account(account["id"])["version"]
    # room is now 0; a single additional cent must be rejected.
    resp = api.create_contribution(
        account["id"], create_contribution_payload(1, v3), ben_headers
    )
    validate_error(resp, ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED.value, 409)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / state_beats_fiscal_on_suspended_overcap_contribution
# ===========================================================================
def test_suspended_overcap_contribution_returns_account_not_open(api):
    """PRD 2.5: "then, for contribution and distribution writes, the account-open check
    (`ERR_ACCOUNT_NOT_OPEN`); and finally the operation's own business rules in the order
    described in their respective workflows below. A check earlier in this precedence always
    masks one later in it."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_overcap_contribution
    """
    _, _, _, account = setup_open_account()
    # Drive regular_contrib_ytd to the cap, then suspend the account.
    post_contribution(account["id"], 1_900_000, account["version"])
    suspended = validate_success(api.suspend_account(account["id"], ADMIN))
    # A contribution that is BOTH over-cap AND against a SUSPENDED account.
    resp = api.create_contribution(
        account["id"], create_contribution_payload(50_000, suspended["version"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN.value, 409)


def test_suspended_overcap_contribution_not_annual_cap_error(api):
    """PRD 2.5: "then, for contribution and distribution writes, the account-open check
    (`ERR_ACCOUNT_NOT_OPEN`); and finally the operation's own business rules in the order
    described in their respective workflows below. A check earlier in this precedence always
    masks one later in it."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_overcap_contribution
    """
    _, _, _, account = setup_open_account()
    post_contribution(account["id"], 1_900_000, account["version"])
    suspended = validate_success(api.suspend_account(account["id"], ADMIN))
    resp = api.create_contribution(
        account["id"], create_contribution_payload(50_000, suspended["version"]), ADMIN
    )
    body = resp.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED.value, (
        "the account-open check masks the later annual-cap check"
    )
    assert body["error_id"] == ApiErrorId.ERR_ACCOUNT_NOT_OPEN.value


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / constraint_beats_fiscal_on_atw_ineligible_overcap
# ===========================================================================
def test_atw_ineligible_participant_returns_ineligible_not_cap(api):
    """PRD 3.6: "For an `ABLE_TO_WORK` contribution, the beneficiary must not be an
    `employer_retirement_plan_participant`; one who is is rejected with `ERR_ATW_INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_atw_ineligible_overcap
    """
    _, _, beneficiary, account = setup_open_account(
        beneficiary_overrides={
            "employer_retirement_plan_participant": True,
            "gross_employment_income_ytd_cents": 0,
        }
    )
    # ATW cap = min(FPL, 0) = 0, so 50_000 would also breach the cap; but the participant
    # check comes first.
    resp = api.create_contribution(
        account["id"],
        create_contribution_payload(50_000, account["version"], contribution_type="ABLE_TO_WORK"),
        make_beneficiary_headers(beneficiary["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ATW_INELIGIBLE.value, 409)


def test_atw_ineligible_takes_precedence_over_atw_cap(api):
    """PRD 3.6: "For an `ABLE_TO_WORK` contribution, the beneficiary must not be an
    `employer_retirement_plan_participant`; one who is is rejected with `ERR_ATW_INELIGIBLE`.
    The ABLE-to-Work ceiling is the smaller of the program's `able_to_work_fpl_cents` and the
    beneficiary's `gross_employment_income_ytd_cents`, and the room remaining is that ceiling
    minus the account's `atw_contrib_ytd_cents`; if `amount_cents` exceeds that room, the
    contribution is rejected with `ERR_ATW_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_atw_ineligible_overcap
    """
    _, _, beneficiary, account = setup_open_account(
        beneficiary_overrides={
            "employer_retirement_plan_participant": True,
            "gross_employment_income_ytd_cents": 0,
        }
    )
    resp = api.create_contribution(
        account["id"],
        create_contribution_payload(50_000, account["version"], contribution_type="ABLE_TO_WORK"),
        make_beneficiary_headers(beneficiary["id"]),
    )
    body = resp.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_ATW_CAP_EXCEEDED.value, (
        "the participant-eligibility check is stated before the ATW cap check"
    )
    assert body["error_id"] == ApiErrorId.ERR_ATW_INELIGIBLE.value


# ===========================================================================
# Difficulty: compensating_invariant / contribution_reverse_conserves_basis_ledger
# ===========================================================================
def test_reverse_contribution_restores_basis_and_ytd(api):
    """PRD 3.6: "Reversal moves the contribution to `REVERSED`, decreases the account's
    `basis_cents` and `balance_cents` by `amount_cents`, decreases the matching year-to-date
    total by `amount_cents` so that cap headroom is restored"

    Design: Difficulty/compensating_invariant/contribution_reverse_conserves_basis_ledger
    """
    _, _, _, account = setup_open_account()
    contrib = post_contribution(account["id"], 500_000, account["version"])
    resp = api.reverse_contribution(contrib["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "REVERSED"
    after = get_account(account["id"])
    assert after["basis_cents"] == 0, f"basis must return to 0, got {after['basis_cents']}"
    assert after["regular_contrib_ytd_cents"] == 0, (
        f"ytd must return to 0, got {after['regular_contrib_ytd_cents']}"
    )


def test_reverse_contribution_restores_balance(api):
    """PRD 3.6: "Reversal moves the contribution to `REVERSED`, decreases the account's
    `basis_cents` and `balance_cents` by `amount_cents`, decreases the matching year-to-date
    total by `amount_cents` so that cap headroom is restored"

    Design: Difficulty/compensating_invariant/contribution_reverse_conserves_basis_ledger
    """
    _, _, _, account = setup_open_account()
    contrib = post_contribution(account["id"], 500_000, account["version"])
    api.reverse_contribution(contrib["id"], ADMIN)
    after = get_account(account["id"])
    assert after["balance_cents"] == 0, f"balance must return to 0, got {after['balance_cents']}"


# ===========================================================================
# Corner: calculations / rollover_counts_with_regular_against_annual_cap
# ===========================================================================
def test_rollover_counts_with_regular_against_annual_cap(api):
    """PRD 3.6: "For a `REGULAR` or `ROLLOVER_529` contribution, the room remaining under the
    annual cap is the program's `annual_contribution_cap_cents` minus the account's
    `regular_contrib_ytd_cents`; if `amount_cents` exceeds that room, the contribution is
    rejected with `ERR_ANNUAL_CAP_EXCEEDED`."

    Design: Corner/calculations/rollover_counts_with_regular_against_annual_cap
    """
    _, _, _, account = setup_open_account()
    post_contribution(account["id"], 500_000, account["version"])
    current_version = get_account(account["id"])["version"]
    # 500_000 + 1_450_000 = 1_950_000 > 1_900_000 cap, even though 1_450_000 < single ceiling.
    resp = api.create_contribution(
        account["id"],
        create_contribution_payload(
            1_450_000, current_version, contribution_type="ROLLOVER_529", source_529_plan="VA529"
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED.value, 409)


# ===========================================================================
# Corner: validations / rollover_over_single_cap_returns_rollover_limit
# (per design index assert: with regular_ytd 0 the annual-cap test wins by ordering)
# ===========================================================================
def test_rollover_over_cap_on_empty_ledger_returns_annual_cap(api):
    """PRD 3.6: "The order of these two rollover checks is fixed — the annual-cap test runs
    first — so a rollover that breaches both yields `ERR_ANNUAL_CAP_EXCEEDED` rather than
    `ERR_ROLLOVER_LIMIT_EXCEEDED`."

    Design: Corner/validations/rollover_over_single_cap_returns_rollover_limit
    """
    _, _, _, account = setup_open_account()
    # regular_ytd is 0, so 2_000_000 breaches both; the annual-cap test (room 1_900_000) wins.
    resp = api.create_contribution(
        account["id"],
        create_contribution_payload(
            2_000_000, account["version"], contribution_type="ROLLOVER_529", source_529_plan="VA529"
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED.value, 409)


# ===========================================================================
# Corner: validations / rollover_missing_source_plan_invalid_request
# ===========================================================================
def test_rollover_missing_source_plan_invalid_request(api):
    """PRD 3.6: "when the type is `ROLLOVER_529` it must additionally carry a non-empty
    `source_529_plan` naming the source plan, and a rollover that omits it is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/rollover_missing_source_plan_invalid_request
    """
    _, _, _, account = setup_open_account()
    resp = api.create_contribution(
        account["id"],
        create_contribution_payload(100_000, account["version"], contribution_type="ROLLOVER_529"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_account_version_on_contribution
# ===========================================================================
def test_occ_stale_account_version_on_contribution_rejected(api):
    """PRD 2.6: "Posting a contribution is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)
    when `expected_account_version` does not equal the account's current `version` — a prior
    writer's contribution will have raised basis and balance and consumed annual-cap headroom,
    so the current writer's view of remaining cap is stale and the create must be refused rather
    than overwrite an unobserved state."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_account_version_on_contribution
    """
    _, _, _, account = setup_open_account()
    original_version = account["version"]
    # First contribution advances the account version.
    post_contribution(account["id"], 100_000, original_version)
    # Second contribution still carries the pre-advance version.
    resp = api.create_contribution(
        account["id"], create_contribution_payload(100_000, original_version), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value, 412)
    after = get_account(account["id"])
    assert after["basis_cents"] == 100_000, (
        f"the stale second contribution must not be recorded, got basis {after['basis_cents']}"
    )


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_correct_version_succeeds_and_increments
# ===========================================================================
def test_occ_correct_version_succeeds_and_increments(api):
    """PRD 3.6: "Posting raises the account's `basis_cents` and `balance_cents` by
    `amount_cents`, raises the matching year-to-date total — `regular_contrib_ytd_cents` for
    `REGULAR` and `ROLLOVER_529`, or `atw_contrib_ytd_cents` for `ABLE_TO_WORK` — by
    `amount_cents`, recomputes `ssi_posture`, and increments the account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_increments
    """
    _, _, _, account = setup_open_account()
    original_version = account["version"]
    resp = api.create_contribution(
        account["id"], create_contribution_payload(100_000, original_version), ADMIN
    )
    validate_success(resp, 201)
    after = get_account(account["id"])
    assert after["version"] == original_version + 1, (
        f"the account version must increment by exactly 1, was {original_version}, now {after['version']}"
    )
