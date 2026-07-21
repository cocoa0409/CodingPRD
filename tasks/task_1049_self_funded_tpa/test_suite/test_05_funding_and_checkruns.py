"""Funding accounts, check-run release/void branches, cascades, OCC, and
fiscal sufficiency."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_fund_cash_identity,
    create_plan, create_provider, create_member, create_adjudicated_claim,
    create_fund_account, deposit, create_check_run, release_check_run,
    setup_funded_adjudicated_claim,
)

ADMIN = TEST_USERS["tpa_admin_headers"]
FUND = TEST_USERS["fund_manager_headers"]

DED_ZERO = {"individual_deductible_cents": 0}


# ---- non_linear_state_machine: check-run DRAFT -> RELEASED vs -> VOIDED -----
def _setup_two_checkruns(api):
    plan = create_plan(individual_deductible_cents=0)
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    c1 = create_adjudicated_claim(member["id"], prov["id"], service_date="2026-03-01",
                                  billed_lines=[{"billed_cents": 100000}])  # plan_paid 48000
    c2 = create_adjudicated_claim(member["id"], prov["id"], service_date="2026-03-02",
                                  billed_lines=[{"billed_cents": 100000}])  # plan_paid 48000
    fund = create_fund_account(plan["id"])
    fund = deposit(fund["id"], 100000)
    cr_release = create_check_run(fund["id"], [c2["id"]])
    cr_void = create_check_run(fund["id"], [c1["id"]])
    return plan, prov, member, c1, c2, fund, cr_release, cr_void


def test_check_run_release_branch_debits_fund_and_pays_claim(api):
    """PRD 3.6: "On a successful release the check-run moves `DRAFT → RELEASED`, its `released_at`
    is stamped with the current clock, and each included claim moves `ADJUDICATED → PAID` with its
    `paid_at` stamped to the current clock."
    PRD 3.6: "The fund's `balance_cents` is reduced by the `total_amount_cents`, its
    `total_disbursed_cents` is increased by the same amount, and its `version` is incremented by one."

    Design: Difficulty/non_linear_state_machine/check_run_branch_release_vs_void
    """
    _plan, _prov, _member, _c1, c2, fund, cr_release, _cr_void = _setup_two_checkruns(api)
    cr = release_check_run(cr_release["id"], fund["version"])
    assert cr["status"] == "RELEASED"
    c2_data = validate_success(api.get_claim(c2["id"], ADMIN))
    assert c2_data["status"] == "PAID"
    fdata = validate_success(api.get_fund_account(fund["id"], ADMIN))
    assert fdata["balance_cents"] == 52000, f"100000 - 48000 -> 52000, got {fdata['balance_cents']}"
    assert fdata["total_disbursed_cents"] == 48000


def test_check_run_void_draft_branch_leaves_fund_and_claim_untouched(api):
    """PRD 3.6: "Voiding a `DRAFT` check-run (`DRAFT → VOIDED`) simply discards the draft: no
    funds move and no claim changes state."

    Design: Difficulty/non_linear_state_machine/check_run_branch_release_vs_void
    """
    _plan, _prov, _member, c1, _c2, _fund, _cr_release, cr_void = _setup_two_checkruns(api)
    cr = validate_success(api.void_check_run(cr_void["id"], FUND))
    assert cr["status"] == "VOIDED"
    c1_data = validate_success(api.get_claim(c1["id"], ADMIN))
    assert c1_data["status"] == "ADJUDICATED", (
        f"voiding a DRAFT check-run leaves its claim ADJUDICATED, got {c1_data['status']}")


# ---- transitive_cascade: release -> claim PAID -> provider ytd -------------
def test_release_cascades_claim_to_paid(api):
    """PRD 3.6: "On a successful release the check-run moves `DRAFT → RELEASED`, its `released_at`
    is stamped with the current clock, and each included claim moves `ADJUDICATED → PAID` with its
    `paid_at` stamped to the current clock."

    Design: Difficulty/transitive_cascade/checkrun_release_cascades_claim_paid_to_provider_ytd_depth2
    """
    _plan, _prov, _member, claim, fund, fund_v = setup_funded_adjudicated_claim(
        deposit_cents=48000, plan_overrides=DED_ZERO)
    cr = create_check_run(fund["id"], [claim["id"]])
    release_check_run(cr["id"], fund_v)
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["status"] == "PAID", f"released claim must be PAID, got {data['status']}"


def test_release_cascades_provider_ytd_paid(api):
    """PRD 3.6: "As a cascade, each newly paid claim increases its provider's `ytd_paid_cents`
    by that claim's `plan_paid_cents`."

    Design: Difficulty/transitive_cascade/checkrun_release_cascades_claim_paid_to_provider_ytd_depth2
    """
    _plan, provider, _member, claim, fund, fund_v = setup_funded_adjudicated_claim(
        deposit_cents=48000, plan_overrides=DED_ZERO)
    cr = create_check_run(fund["id"], [claim["id"]])
    release_check_run(cr["id"], fund_v)
    data = validate_success(api.get_provider(provider["id"], ADMIN))
    assert data["ytd_paid_cents"] == 48000, (
        f"provider ytd increases by plan_paid 48000, got {data['ytd_paid_cents']}")


# ---- compensating_invariant: fund cash conservation on release then void ---
def _setup_released_then_ready_to_void(api):
    plan, _prov, _member, claim, fund, fund_v = setup_funded_adjudicated_claim(
        deposit_cents=100000, plan_overrides=DED_ZERO)
    cr = create_check_run(fund["id"], [claim["id"]])
    release_check_run(cr["id"], fund_v)   # balance 52000, disbursed 48000
    return claim, fund, cr


def test_fund_conservation_balance_restored_after_release_then_void(api):
    """PRD 3.6: "Voiding a `RELEASED` check-run (`RELEASED → VOIDED`) is fully compensating: each
    included claim moves `PAID → ADJUDICATED` and its `paid_at` is cleared; each such claim's
    provider has its `ytd_paid_cents` decreased by that claim's `plan_paid_cents`; the fund's
    `balance_cents` is increased by the `total_amount_cents` and its `total_disbursed_cents`
    decreased by the same amount; and the fund's `version` is incremented by one."

    Design: Difficulty/compensating_invariant/fund_cash_conservation_on_release_then_void
    """
    _claim, fund, cr = _setup_released_then_ready_to_void(api)
    validate_success(api.void_check_run(cr["id"], FUND))
    fdata = validate_success(api.get_fund_account(fund["id"], ADMIN))
    assert fdata["balance_cents"] == 100000
    assert fdata["total_disbursed_cents"] == 0
    assert fdata["total_deposited_cents"] == 100000
    assert_fund_cash_identity(fdata)


def test_void_released_restores_claim_to_adjudicated(api):
    """PRD 3.6: "Voiding a `RELEASED` check-run (`RELEASED → VOIDED`) is fully compensating: each
    included claim moves `PAID → ADJUDICATED` and its `paid_at` is cleared; each such claim's
    provider has its `ytd_paid_cents` decreased by that claim's `plan_paid_cents`; the fund's
    `balance_cents` is increased by the `total_amount_cents` and its `total_disbursed_cents`
    decreased by the same amount; and the fund's `version` is incremented by one."

    Design: Difficulty/compensating_invariant/fund_cash_conservation_on_release_then_void
    """
    claim, _fund, cr = _setup_released_then_ready_to_void(api)
    validate_success(api.void_check_run(cr["id"], FUND))
    data = validate_success(api.get_claim(claim["id"], ADMIN))
    assert data["status"] == "ADJUDICATED", (
        f"voiding a RELEASED check-run returns its claim to ADJUDICATED, got {data['status']}")


# ---- Corner: OCC stale / correct fund version ------------------------------
def test_release_with_stale_fund_version_returns_412(api):
    """PRD 2.5: "If they do not match — because another check-run has already been released
    against the same fund, or a deposit has posted, since the client last read it — the release
    is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_fund_version_on_release_returns_412
    """
    plan = create_plan(individual_deductible_cents=0)
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = create_adjudicated_claim(member["id"], prov["id"],
                                     billed_lines=[{"billed_cents": 100000}])
    fund = create_fund_account(plan["id"])
    fund = deposit(fund["id"], 60000)
    fa_v_stale = fund["version"]
    cr = create_check_run(fund["id"], [claim["id"]])
    deposit(fund["id"], 1)  # advances fund version, making fa_v_stale stale
    resp = api.release_check_run(cr["id"], {"expected_fund_account_version": fa_v_stale}, FUND)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    cdata = validate_success(api.get_claim(claim["id"], ADMIN))
    assert cdata["status"] == "ADJUDICATED", (
        f"a rejected release does not pay the claim, got {cdata['status']}")


def test_release_with_correct_fund_version_succeeds_and_bumps_version(api):
    """PRD 3.6: "The fund's `balance_cents` is reduced by the `total_amount_cents`, its
    `total_disbursed_cents` is increased by the same amount, and its `version` is incremented by one."
    PRD 2.5: "The release request must carry `expected_fund_account_version`, which is the
    `version` of the target fund account that the client last observed."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_fund_version_release_succeeds_and_bumps_version
    """
    plan = create_plan(individual_deductible_cents=0)
    prov = create_provider(in_network=True, ppo_discount_pct=0.40)
    member = create_member(plan["id"])
    claim = create_adjudicated_claim(member["id"], prov["id"],
                                     billed_lines=[{"billed_cents": 100000}])
    fund = create_fund_account(plan["id"])
    fund = deposit(fund["id"], 60000)
    fa_v = fund["version"]
    cr = create_check_run(fund["id"], [claim["id"]])
    released = release_check_run(cr["id"], fa_v)
    assert released["status"] == "RELEASED"
    fdata = validate_success(api.get_fund_account(fund["id"], ADMIN))
    assert fdata["balance_cents"] == 12000, f"60000 - 48000 -> 12000, got {fdata['balance_cents']}"
    assert fdata["version"] == fa_v + 1, (
        f"release increments fund version by 1 (from {fa_v}), got {fdata['version']}")


# ---- Corner: check-run membership + fiscal sufficiency ---------------------
def test_second_check_run_with_same_claim_returns_already_in_check_run(api):
    """PRD 3.6: "A claim may not appear in more than one live check-run: if any of the supplied
    `claim_ids` already belongs to a check-run that is `DRAFT` or `RELEASED`, the draft is
    rejected with `ERR_CLAIM_ALREADY_IN_CHECK_RUN`."

    Design: Corner/endpoints/create_second_check_run_with_same_claim_returns_already_in_check_run
    """
    _plan, _prov, _member, claim, fund, _fund_v = setup_funded_adjudicated_claim(
        deposit_cents=100000, plan_overrides=DED_ZERO)
    create_check_run(fund["id"], [claim["id"]])  # first (DRAFT) check-run holds the claim
    resp = api.create_check_run(
        {"fund_account_id": fund["id"], "claim_ids": [claim["id"]]}, FUND)
    validate_error(resp, ApiErrorId.ERR_CLAIM_ALREADY_IN_CHECK_RUN.value)


def test_release_check_run_insufficient_funds_returns_402(api):
    """PRD 3.6: "The fund's `balance_cents` must be at least the check-run's `total_amount_cents`;
    if it is short, the release is rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402)."

    Design: Corner/validations/release_check_run_insufficient_funds_returns_402
    """
    _plan, _prov, _member, claim, fund, fund_v = setup_funded_adjudicated_claim(
        deposit_cents=100, plan_overrides=DED_ZERO)  # balance 100 < total 48000
    cr = create_check_run(fund["id"], [claim["id"]])
    resp = api.release_check_run(cr["id"], {"expected_fund_account_version": fund_v}, FUND)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
