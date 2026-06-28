"""Distribution lifecycle: the branching state machine, the pro-rata earnings split,
substantiation, clawback penalty, and cross-entity account-state guards.

Difficulty (queue A) instances appear with >=2 tests each; corner (queue B)
instances appear once. Each docstring ends with its Design tag.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_distribution_payload,
    create_qde_record_payload,
    make_program_admin_headers,
    make_beneficiary_headers,
    setup_open_account,
    setup_disbursed_distribution,
    post_contribution,
    credit_earnings,
    request_distribution,
    approve_distribution,
    disburse_distribution,
    attach_qde_record,
    get_account,
    get_distribution,
)

ADMIN = make_program_admin_headers()


# ===========================================================================
# Difficulty: non_linear_state_machine / distribution_fork_join_disburse_vs_reject
# ===========================================================================
def test_distribution_fork_one_disbursed(api):
    """PRD 3.8: "Disbursement, performed by the owning `Beneficiary` or an
    `AuthorizedRepresentative`, moves the distribution from `APPROVED` to `DISBURSED` and is
    the moment money leaves the account."

    Design: Difficulty/non_linear_state_machine/distribution_fork_join_disburse_vs_reject
    """
    _, _, beneficiary, account = setup_open_account()
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    post_contribution(account["id"], 1_900_000, account["version"], headers=ben_headers)
    dist_a = request_distribution(account["id"], 1_000_000, beneficiary["id"], category="HEALTH")
    approve_distribution(dist_a["id"], beneficiary["id"])
    current_version = get_account(account["id"])["version"]
    resp = api.disburse_distribution(
        dist_a["id"], {"expected_account_version": current_version}, ben_headers
    )
    data = validate_success(resp)
    assert data["status"] == "DISBURSED"


def test_distribution_fork_other_rejected(api):
    """PRD 3.8: "A `ProgramAdministrator` may instead reject a still-`REQUESTED` distribution,
    moving it to `REJECTED`, which is terminal."

    Design: Difficulty/non_linear_state_machine/distribution_fork_join_disburse_vs_reject
    """
    _, _, beneficiary, account = setup_open_account()
    post_contribution(account["id"], 1_900_000, account["version"])
    dist_b = request_distribution(account["id"], 500_000, beneficiary["id"], category="EDUCATION")
    resp = api.reject_distribution(dist_b["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "REJECTED"


# ===========================================================================
# Difficulty: dual_variant_calc / earnings_split_snapshot_vs_recompute
# ===========================================================================
def test_earnings_portion_captured_at_disbursement(api):
    """PRD 3.8: "The earnings ratio is zero when the account's `balance_cents` is zero, and
    otherwise is the account's `earnings_cents` divided by its `balance_cents`. The
    distribution's `earnings_portion_cents` is `amount_cents` multiplied by that ratio,
    rounded half up to whole cents"

    Design: Difficulty/dual_variant_calc/earnings_split_snapshot_vs_recompute
    """
    # basis 1_900_000 + earnings 600_000 = balance 2_500_000; ratio 600_000/2_500_000 = 0.24.
    _, _, beneficiary, account = setup_open_account()
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    post_contribution(account["id"], 1_900_000, account["version"], headers=ben_headers)
    credit_earnings(account["id"], 600_000)
    account = get_account(account["id"])
    dist = request_distribution(account["id"], 1_000_000, beneficiary["id"], category="HEALTH")
    approve_distribution(dist["id"], beneficiary["id"])
    resp = api.disburse_distribution(
        dist["id"], {"expected_account_version": account["version"]}, ben_headers
    )
    data = validate_success(resp)
    # 1_000_000 * 0.24 = 240_000.
    assert data["earnings_portion_cents"] == 240_000, (
        f"earnings_portion_cents must be 240000, got {data['earnings_portion_cents']}"
    )


def test_earnings_portion_is_snapshot_not_recomputed(api):
    """PRD 3.8: "At disbursement the system captures a pro-rata earnings split, fixed at that
    instant so that later balance changes never retroactively move this distribution's split."

    Design: Difficulty/dual_variant_calc/earnings_split_snapshot_vs_recompute
    """
    _, _, beneficiary, account = setup_open_account()
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    post_contribution(account["id"], 1_900_000, account["version"], headers=ben_headers)
    credit_earnings(account["id"], 600_000)
    account = get_account(account["id"])
    dist = request_distribution(account["id"], 1_000_000, beneficiary["id"], category="HEALTH")
    approve_distribution(dist["id"], beneficiary["id"])
    disburse_distribution(dist["id"], account["version"], beneficiary["id"])
    # A later earnings credit must NOT move the captured split.
    credit_earnings(account["id"], 900_000)
    after = get_distribution(dist["id"], ben_headers)
    assert after["earnings_portion_cents"] == 240_000, (
        f"earnings_portion_cents must remain the snapshot 240000 after a later credit, "
        f"got {after['earnings_portion_cents']}"
    )


# ===========================================================================
# Difficulty: cross_entity_state_dependency / distribution_approve_requires_account_open
# ===========================================================================
def test_approve_distribution_on_suspended_account_rejected(api):
    """PRD 3.8: "Approval, performed by the owning `Beneficiary` or an
    `AuthorizedRepresentative`, moves the distribution from `REQUESTED` to `APPROVED`, but only
    when the account is `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`) and the requested
    `amount_cents` does not exceed the account's `balance_cents` (otherwise
    `ERR_INSUFFICIENT_BALANCE`)."

    Design: Difficulty/cross_entity_state_dependency/distribution_approve_requires_account_open
    """
    _, _, beneficiary, account = setup_open_account()
    post_contribution(account["id"], 1_000_000, account["version"])
    dist = request_distribution(account["id"], 200_000, beneficiary["id"], category="HEALTH")
    api.suspend_account(account["id"], ADMIN)
    resp = api.approve_distribution(dist["id"], make_beneficiary_headers(beneficiary["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_OPEN.value, 409)


def test_approve_blocked_distribution_stays_requested(api):
    """PRD 3.8: "Approval, performed by the owning `Beneficiary` or an
    `AuthorizedRepresentative`, moves the distribution from `REQUESTED` to `APPROVED`, but only
    when the account is `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`) and the requested
    `amount_cents` does not exceed the account's `balance_cents` (otherwise
    `ERR_INSUFFICIENT_BALANCE`)."

    Design: Difficulty/cross_entity_state_dependency/distribution_approve_requires_account_open
    """
    _, _, beneficiary, account = setup_open_account()
    post_contribution(account["id"], 1_000_000, account["version"])
    dist = request_distribution(account["id"], 200_000, beneficiary["id"], category="HEALTH")
    api.suspend_account(account["id"], ADMIN)
    api.approve_distribution(dist["id"], make_beneficiary_headers(beneficiary["id"]))
    after = get_distribution(dist["id"], make_beneficiary_headers(beneficiary["id"]))
    assert after["status"] == "REQUESTED", (
        f"a blocked approval must leave the distribution REQUESTED, got {after['status']}"
    )


# ===========================================================================
# Corner: state_machines / disburse_requested_distribution_invalid_state
# ===========================================================================
def test_disburse_requested_distribution_invalid_state(api):
    """PRD 3.8: "Disbursement, performed by the owning `Beneficiary` or an
    `AuthorizedRepresentative`, moves the distribution from `APPROVED` to `DISBURSED` and is
    the moment money leaves the account."
    PRD 2.5: "then, for a state-transition endpoint, whether the target resource is in a legal
    state for the transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/disburse_requested_distribution_invalid_state
    """
    _, _, beneficiary, account = setup_open_account()
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    funded = post_contribution(account["id"], 1_000_000, account["version"], headers=ben_headers)
    dist = request_distribution(account["id"], 200_000, beneficiary["id"], category="HEALTH")
    # Never approved — disburse must fail on state.
    resp = api.disburse_distribution(
        dist["id"], {"expected_account_version": funded["version"]}, ben_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = get_distribution(dist["id"], ben_headers)
    assert after["status"] == "REQUESTED"


# ===========================================================================
# Corner: state_machines / distribution_substantiate_full_qde_success
# ===========================================================================
def test_distribution_substantiate_full_qde_success(api):
    """PRD 3.8: "substantiation moves it from `DISBURSED` to `SUBSTANTIATED`, but only when the
    sum of the `amount_cents` of every `QDERecord` attached to the distribution equals the
    distribution's own `amount_cents` (otherwise `ERR_QDE_MISMATCH`). On substantiation the
    distribution's `qualified_amount_cents` is set to its full `amount_cents`, its
    `nonqualified_amount_cents` to zero, and its `additional_tax_cents` to zero."

    Design: Corner/state_machines/distribution_substantiate_full_qde_success
    """
    _, _, beneficiary, account, dist = setup_disbursed_distribution(
        distribution_amount_cents=1_000_000, basis_cents=1_900_000, earnings_delta_cents=600_000,
    )
    attach_qde_record(dist["id"], 600_000, beneficiary["id"], receipt_reference="R-1")
    attach_qde_record(dist["id"], 400_000, beneficiary["id"], receipt_reference="R-2",
                      expense_date="2026-02-02")
    resp = api.substantiate_distribution(dist["id"], make_beneficiary_headers(beneficiary["id"]))
    data = validate_success(resp)
    assert data["status"] == "SUBSTANTIATED"
    assert data["qualified_amount_cents"] == 1_000_000
    assert data["nonqualified_amount_cents"] == 0
    assert data["additional_tax_cents"] == 0


# ===========================================================================
# Corner: state_machines / distribution_clawback_partial_qde_penalty
# ===========================================================================
def test_distribution_clawback_partial_qde_penalty(api):
    """PRD 3.10: "The `nonqualified_amount_cents` is the distribution's `amount_cents` minus
    that qualified sum, floored at zero."
    PRD 3.10: "the non-qualified earnings are the distribution's `earnings_portion_cents` (the
    split captured at disbursement) multiplied by the ratio of `nonqualified_amount_cents` to
    the distribution's `amount_cents`. The `additional_tax_cents` is those non-qualified
    earnings multiplied by the program's `nonqualified_additional_tax_pct`, rounded half up to
    whole cents."

    Design: Corner/state_machines/distribution_clawback_partial_qde_penalty
    """
    # earnings_portion 240_000; one QDE of 600_000 -> nonqualified 400_000;
    # nonqual earnings = 240_000 * (400_000/1_000_000) = 96_000; tax = 96_000 * 0.10 = 9_600.
    _, _, beneficiary, account, dist = setup_disbursed_distribution(
        distribution_amount_cents=1_000_000, basis_cents=1_900_000, earnings_delta_cents=600_000,
        category="OTHER",
    )
    attach_qde_record(dist["id"], 600_000, beneficiary["id"], receipt_reference="R-1")
    resp = api.clawback_distribution(dist["id"], ADMIN)
    data = validate_success(resp)
    assert data["status"] == "CLAWED_BACK"
    assert data["nonqualified_amount_cents"] == 400_000
    assert data["additional_tax_cents"] == 9_600


# ===========================================================================
# Corner: validations / qde_mismatch_on_substantiate
# ===========================================================================
def test_qde_mismatch_on_substantiate(api):
    """PRD 3.8: "substantiation moves it from `DISBURSED` to `SUBSTANTIATED`, but only when the
    sum of the `amount_cents` of every `QDERecord` attached to the distribution equals the
    distribution's own `amount_cents` (otherwise `ERR_QDE_MISMATCH`)."

    Design: Corner/validations/qde_mismatch_on_substantiate
    """
    _, _, beneficiary, account, dist = setup_disbursed_distribution(
        distribution_amount_cents=1_000_000, basis_cents=1_900_000, earnings_delta_cents=0,
    )
    attach_qde_record(dist["id"], 600_000, beneficiary["id"], receipt_reference="R-1")
    resp = api.substantiate_distribution(dist["id"], make_beneficiary_headers(beneficiary["id"]))
    validate_error(resp, ApiErrorId.ERR_QDE_MISMATCH.value, 409)


# ===========================================================================
# Corner: validations / insufficient_balance_on_distribution_approve
# ===========================================================================
def test_insufficient_balance_on_distribution_approve(api):
    """PRD 3.8: "Approval, performed by the owning `Beneficiary` or an
    `AuthorizedRepresentative`, moves the distribution from `REQUESTED` to `APPROVED`, but only
    when the account is `OPEN` (otherwise `ERR_ACCOUNT_NOT_OPEN`) and the requested
    `amount_cents` does not exceed the account's `balance_cents` (otherwise
    `ERR_INSUFFICIENT_BALANCE`)."

    Design: Corner/validations/insufficient_balance_on_distribution_approve
    """
    _, _, beneficiary, account = setup_open_account()
    post_contribution(account["id"], 1_000_000, account["version"])
    dist = request_distribution(account["id"], 2_000_000, beneficiary["id"], category="HEALTH")
    resp = api.approve_distribution(dist["id"], make_beneficiary_headers(beneficiary["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value, 409)
