"""Additional difficulty-instance coverage — second test per instance.

Each difficulty instance must be exercised by at least two tests with distinct
angles. The first test typically locks the trigger's primary error/outcome;
this file adds a complementary observation (e.g., side-effect on a referenced
entity, lock-down invariant, or sibling negative case)."""
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
    initiate_conversion,
    complete_conversion,
    get_account,
    get_owner,
    get_rmd_schedule,
    create_rmd_schedule,
    advance_year_rollover,
    setup_inherited_traditional_with_secure_deadline,
    make_account_owner_headers,
)


# =============================================================================
# Difficulty Rule 1 instance #1 — companion: source account state after Conv A
# =============================================================================


def test_pro_rata_single_variant_drains_source_basis_on_complete(api):
    """PRD §3.5: "decrements the source's `cash_balance_cents` by
    `gross_amount_cents`, decrements the source's `pretax_basis_cents` by the
    share proportional to the taxable split and the source's
    `aftertax_basis_cents` by the share proportional to the nontaxable
    split, increments the target Roth's `cash_balance_cents` by
    `gross_amount_cents`, returns the source's `status` to `ACTIVE`..."

    Aftertax-only single-account variant: nontaxable=gross, taxable=0; the
    source's aftertax_basis_cents must drop by the full gross while
    pretax_basis_cents stays at zero.

    Design: Difficulty/dual_variant_calc/backdoor_roth_pro_rata_variant_divergence_on_conversion
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="AliceCompanion",
        date_of_birth="1981-03-10",
        tax_id_last4="1234",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    roth = create_account(owner["id"], "ROTH")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="AFTERTAX",
    )

    conv = initiate_conversion(
        source_account_id=trad["id"],
        target_account_id=roth["id"],
        owner_id=owner["id"],
        gross_amount_cents=200_000,
    )
    refreshed = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    complete_conversion(conv["id"], owner["id"], refreshed["version"])

    final_trad = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    # Aftertax basis fully consumed; pretax untouched.
    assert final_trad["aftertax_basis_cents"] == 0
    assert final_trad["pretax_basis_cents"] == 0
    assert final_trad["cash_balance_cents"] == 0
    # Source status returned to ACTIVE per the complete side-effect.
    assert final_trad["status"] == "ACTIVE"

    final_roth = get_account(roth["id"], make_account_owner_headers(owner["id"]))
    assert final_roth["cash_balance_cents"] == 200_000


# =============================================================================
# Difficulty Rule 2 instance #1 — companion: a within-band AGI of exactly the
# floor returns the full headroom
# =============================================================================


def test_roth_phaseout_at_floor_passes_full_headroom(api):
    """PRD §3.3: "If `modified_agi_cents` is less than or equal to the floor,
    the full headroom passes through unreduced."
    PRD §3.3: "For 2026 the brackets are: `SINGLE` and `HEAD_OF_HOUSEHOLD`
    15,400,000 cents to 16,900,000 cents..."
    PRD §3.3: "A base limit applies to every owner: 700,000 cents (seven
    thousand dollars) for tax years 2024 and 2025, and 750,000 cents (seven
    thousand five hundred dollars) for tax year 2026. A catch-up addition is
    granted when the owner is at least fifty years old at year-end: 100,000
    cents (one thousand dollars) for tax years 2024 and 2025, and 110,000
    cents (eleven hundred dollars) for tax year 2026; an owner younger than
    fifty receives no catch-up."

    SINGLE 2026 owner under age 50 at AGI 15,400,000 (exactly the floor) gets
    full headroom 750,000; a 750,000 ROTH contribution must confirm.

    Design: Difficulty/combinatorial_formula/roth_eligibility_three_input_phaseout_with_floor_to_1000
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="CarolFloor",
        date_of_birth="1981-04-04",
        tax_id_last4="9990",
        filing_status="SINGLE",
        modified_agi_cents=15_400_000,
    )
    roth = create_account(owner["id"], "ROTH")
    pending = create_pending_contribution(
        account_id=roth["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=750_000,
        contribution_kind="ROTH",
    )
    confirmed = confirm_contribution(pending["id"], owner["id"], roth["version"])
    assert confirmed["status"] == "CONFIRMED"


# =============================================================================
# Difficulty Rule 2 instance #2 — companion: target ROTH receives the gross
# =============================================================================


def test_pro_rata_sum_then_divide_drains_source_and_credits_target_roth(api):
    """PRD §3.5: "decrements the source's `cash_balance_cents` by
    `gross_amount_cents`, decrements the source's `pretax_basis_cents` by the
    share proportional to the taxable split and the source's
    `aftertax_basis_cents` by the share proportional to the nontaxable
    split, increments the target Roth's `cash_balance_cents` by
    `gross_amount_cents`..."

    The complementary balance side of the sum-then-divide conversion: source
    cash drops by gross, target Roth cash gains gross.

    Design: Difficulty/combinatorial_formula/backdoor_roth_pro_rata_nested_rounding_order_on_conversion
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="DaveCompanion",
        date_of_birth="1981-07-22",
        tax_id_last4="2202",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    roth = create_account(owner["id"], "ROTH")

    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=500_000,
        contribution_kind="PRETAX",
    )
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="AFTERTAX",
    )
    advance_year_rollover(2027)
    set_clock("2027-01-15T00:00:00Z")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2027,
        amount_cents=200_000,
        contribution_kind="AFTERTAX",
    )

    conv = initiate_conversion(
        source_account_id=trad["id"],
        target_account_id=roth["id"],
        owner_id=owner["id"],
        gross_amount_cents=200_000,
    )
    refreshed = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    complete_conversion(conv["id"], owner["id"], refreshed["version"])

    final_roth = get_account(roth["id"], make_account_owner_headers(owner["id"]))
    assert final_roth["cash_balance_cents"] == 200_000, (
        f"target ROTH must receive the full gross 200000, "
        f"got {final_roth['cash_balance_cents']}"
    )


# =============================================================================
# Difficulty Rule 4 instance #1 — companion: rmd_posture flips on declare-deceased
# =============================================================================


def test_declare_deceased_sets_rmd_posture_required_pending_under_secure(api):
    """PRD §3.6: "every `OPEN` `RMDSchedule` for this owner is recomputed
    under the inherited timeline."
    PRD §3.7: "If the resulting `required_amount_cents` is strictly greater
    than zero, `AccountOwner.rmd_posture` is set to `REQUIRED_PENDING`."

    Companion to the depth-≥4 cascade: after declare-deceased, the SECURE
    recompute produces a positive required amount (63636 in year 1 against
    700000), and the rebuilt schedule's positive requirement keeps the
    owner's rmd_posture at REQUIRED_PENDING.

    Design: Difficulty/transitive_cascade/declare_deceased_depth4_cascade_through_inherited_beneficiary_rmd
    """
    owner, account, beneficiary = (
        setup_inherited_traditional_with_secure_deadline(
            iso8601_alive="2026-06-01T00:00:00Z",
            deceased_at="2026-06-01T12:00:00Z",
            date_of_birth="1953-04-04",
            cash_cents=700_000,
            funding_tax_year=2026,
            full_name="GinaCompanion",
            tax_id_last4="5550",
        )
    )
    sched = create_rmd_schedule(owner["id"], 2026)
    # Per PRD §3.7, secure_10year_pace year-1 even allocation: the gap from
    # current_utc (2026-06-01T00:00:00Z) to secure_deadline_at (deceased_at
    # 2026-06-01T12:00:00Z + 10y = 2036-06-01T12:00:00Z) is 3653.5 days;
    # 3653.5 / 365 rounded UP = 11 years remaining; 700000 // 11 = 63636
    # (strictly positive, which is what drives REQUIRED_PENDING below).
    assert sched["required_amount_cents"] == 63_636
    owner_after = get_owner(owner["id"])
    # PRD §3.7: positive required → REQUIRED_PENDING.
    assert owner_after["rmd_posture"] == "REQUIRED_PENDING"


# =============================================================================
# Difficulty Rule 4 instance #2 — companion: cash_balance decremented exactly
# =============================================================================


def test_rmd_distribution_confirm_decrements_cash_by_amount(api):
    """PRD §3.4: "On a successful confirm, `confirmed_at` is stamped, the
    distribution moves to `CONFIRMED`, `cash_balance_cents` decreases by
    `amount_cents`..."

    Design: Difficulty/transitive_cascade/distribution_confirm_rmd_satisfaction_depth3_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="HenryCompanion",
        date_of_birth="1953-05-05",
        tax_id_last4="6660",
        filing_status="SINGLE",
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )
    sched = create_rmd_schedule(owner["id"], 2026)
    required = sched["required_amount_cents"]

    refreshed = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        amount_cents=required,
        distribution_reason="RMD",
        tax_year=2026,
    )
    confirm_distribution(pending["id"], owner["id"], refreshed["version"])

    final_acct = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    assert final_acct["cash_balance_cents"] == 700_000 - required


# =============================================================================
# Difficulty Rule 5 instance #2 — companion: distribution status remains
# CONFIRMED after the rejected re-confirm
# =============================================================================


def test_re_confirm_already_confirmed_distribution_leaves_status_confirmed(api):
    """PRD §3.4: "On a successful confirm, `confirmed_at` is stamped, the
    distribution moves to `CONFIRMED`..."
    PRD §2.6: "Third, state: for action endpoints the target entity must be in
    the from-state declared by the relevant transition, with rejection code
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_insufficient_balance_on_distribution_confirm
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="JaneCompanion",
        date_of_birth="1981-09-09",
        tax_id_last4="8880",
        filing_status="SINGLE",
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )

    refreshed_v1 = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        amount_cents=50_000,
        distribution_reason="NORMAL",
        tax_year=2026,
    )
    confirm_distribution(pending["id"], owner["id"], refreshed_v1["version"])

    refreshed_v2 = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    res = api.confirm_distribution(
        pending["id"],
        {"expected_account_version": refreshed_v2["version"]},
        make_account_owner_headers(owner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    # The original distribution row remains CONFIRMED — failed re-confirm doesn't mutate it.
    fetched = api.get_distribution(pending["id"], make_account_owner_headers(owner["id"]))
    confirmed_dist = validate_success(fetched, expected_status=200)
    assert confirmed_dist["status"] == "CONFIRMED"


# =============================================================================
# Difficulty Rule 7 instance #1 — companion: conversion stays INITIATED after
# the rejected complete
# =============================================================================


def test_conversion_stays_initiated_when_complete_blocked_by_frozen_target(api):
    """PRD §3.5: "While the conversion is in `INITIATED` the owner may either
    complete it or reverse it."
    PRD §3.5: "Completion (initiated to `COMPLETED`) requires the target Roth
    account to be `ACTIVE` and consumes `expected_source_account_version`."

    A blocked complete must not advance the conversion past INITIATED.

    Design: Difficulty/cross_entity_state_dependency/conversion_completes_only_when_target_roth_account_active
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="NoahCompanion",
        date_of_birth="1981-11-11",
        tax_id_last4="1410",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    roth = create_account(owner["id"], "ROTH")
    roth_v0 = roth["version"]

    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="AFTERTAX",
    )
    conv = initiate_conversion(
        source_account_id=trad["id"],
        target_account_id=roth["id"],
        owner_id=owner["id"],
        gross_amount_cents=200_000,
    )
    api.freeze_account(
        roth["id"],
        {"expected_account_version": roth_v0},
        TEST_USERS["plan_admin_headers"],
    )
    refreshed_trad = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    api.complete_conversion(
        conv["id"],
        {"expected_source_account_version": refreshed_trad["version"]},
        make_account_owner_headers(owner["id"]),
    )
    # Conversion still in INITIATED.
    fetched = api.get_conversion(conv["id"], make_account_owner_headers(owner["id"]))
    same = validate_success(fetched, expected_status=200)
    assert same["status"] == "INITIATED"


# =============================================================================
# Difficulty Rule 7 instance #2 — companion: distribution stays PENDING after
# the rejected confirm
# =============================================================================


def test_rmd_distribution_stays_pending_when_no_open_schedule(api):
    """PRD §3.4: "The distribution is created in `PENDING`."
    PRD §3.4: "Second, if `distribution_reason` is `RMD` there must be an
    `OPEN` (or, on a late-cure, a `DELINQUENT`) `RMDSchedule` for this owner
    and this `tax_year`; the schedule is what the satisfied amount
    accumulates against."

    Design: Difficulty/cross_entity_state_dependency/rmd_distribution_confirm_requires_open_rmd_schedule
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="OliveCompanion",
        date_of_birth="1953-06-06",
        tax_id_last4="1510",
        filing_status="SINGLE",
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )
    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        amount_cents=26_315,
        distribution_reason="RMD",
        tax_year=2026,
    )
    refreshed = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    api.confirm_distribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(owner["id"]),
    )
    fetched = api.get_distribution(pending["id"], make_account_owner_headers(owner["id"]))
    same = validate_success(fetched, expected_status=200)
    assert same["status"] == "PENDING"


# =============================================================================
# Difficulty Rule 8 instance #1 — companion: ytd preserved on failed confirm
# =============================================================================


def test_failed_cap_breach_does_not_advance_ytd(api):
    """PRD §2.7: "if they differ, the confirm is rejected with
    `ERR_STALE_VERSION` and HTTP 412, and no balances or audit records are
    touched." (Same no-write-on-failure guarantee applies symmetrically to
    other rejected confirms.)
    PRD §3.3: "the sum of the account's existing `ytd_contribution_cents`
    and the contribution's `amount_cents` must not exceed the per-year
    contribution limit for this owner, account type, and tax year (see below);
    breach yields `ERR_CONTRIBUTION_CAP_EXCEEDED`."

    A rejected cap-breach confirm must leave ytd at the prior value.

    Design: Difficulty/resource_temporal_overlap/contribution_tax_year_window_aggregate_capacity_overlap_on_contribution
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="PeterCompanion",
        date_of_birth="1981-12-12",
        tax_id_last4="1610",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )
    refreshed = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    ytd_pre = refreshed["ytd_contribution_cents"]

    pending = create_pending_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=60_000,
        contribution_kind="PRETAX",
    )
    api.confirm_contribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(owner["id"]),
    )
    after = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    assert after["ytd_contribution_cents"] == ytd_pre, (
        f"failed cap-breach confirm must leave ytd unchanged "
        f"(pre={ytd_pre}, post={after['ytd_contribution_cents']})"
    )


# =============================================================================
# Difficulty Rule 8 instance #2 — companion: cash balance unchanged on the
# blocked SECURE-deadline distribution
# =============================================================================


def test_blocked_secure_deadline_distribution_leaves_balance_intact(api):
    """PRD §3.4: "On a successful confirm, `confirmed_at` is stamped, the
    distribution moves to `CONFIRMED`, `cash_balance_cents` decreases by
    `amount_cents`..." — a rejected confirm performs none of these effects.
    PRD §3.4: "Third, on an `INHERITED` Traditional account whose active
    beneficiary relationship is `NON_ELIGIBLE_INDIVIDUAL`, the SECURE Act
    ten-year rule forbids a confirm that would leave any positive
    `cash_balance_cents` standing past the beneficiary's `secure_deadline_at`
    — measured against the system clock at confirmation — and such a confirm
    is rejected with `ERR_SECURE_DEADLINE_PASSED`."

    Design: Difficulty/resource_temporal_overlap/secure_10year_deadline_closed_endpoint_overlap_on_distribution
    """
    owner, account, beneficiary = (
        setup_inherited_traditional_with_secure_deadline(
            iso8601_alive="2026-06-01T00:00:00Z",
            deceased_at="2026-06-01T12:00:00Z",
            date_of_birth="1953-07-07",
            cash_cents=700_000,
            funding_tax_year=2026,
            full_name="QuinnCompanion",
            tax_id_last4="1710",
        )
    )
    pre_cash = account["cash_balance_cents"]
    assert pre_cash == 700_000

    set_clock("2036-06-02T00:00:00Z")
    refreshed = get_account(account["id"], TEST_USERS["plan_admin_headers"])
    pending = create_pending_distribution(
        account_id=account["id"],
        owner_id=owner["id"],
        amount_cents=10_000,
        distribution_reason="INHERITED",
        tax_year=2036,
    )
    api.confirm_distribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(owner["id"]),
    )
    after = get_account(account["id"], TEST_USERS["plan_admin_headers"])
    assert after["cash_balance_cents"] == pre_cash, (
        f"rejected SECURE-deadline confirm must not change cash_balance_cents "
        f"(pre={pre_cash}, post={after['cash_balance_cents']})"
    )


# =============================================================================
# Difficulty Rule 9 instance #1 — companion: contribution status is REVERSED
# =============================================================================


def test_contribution_reverse_advances_contribution_status_to_reversed(api):
    """PRD §3.3: "Reversal walks the same balance arithmetic in the opposite
    direction: `cash_balance_cents`, `ytd_contribution_cents`, and the
    relevant basis bucket each lose `amount_cents`; the contribution moves to
    `REVERSED`; `updated_at` is refreshed; `version` increments by 1."

    Design: Difficulty/compensating_invariant/contribution_confirm_then_reverse_conserves_account_balance_and_ytd
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="RogerCompanion",
        date_of_birth="1981-01-01",
        tax_id_last4="1810",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    pending = create_pending_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="PRETAX",
    )
    confirm_contribution(pending["id"], owner["id"], trad["version"])
    mid = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    rev_res = api.reverse_contribution(
        pending["id"],
        {"expected_account_version": mid["version"]},
        TEST_USERS["plan_admin_headers"],
    )
    reversed_data = validate_success(rev_res, expected_status=200)
    assert reversed_data["status"] == "REVERSED"


# =============================================================================
# Difficulty Rule 9 instance #2 — companion: distribution status is REVERSED
# and cash is restored
# =============================================================================


def test_rmd_distribution_reverse_restores_cash_balance(api):
    """PRD §3.4: "Reversal moves the distribution to `REVERSED`, restores
    `cash_balance_cents` by `amount_cents`..."

    Design: Difficulty/compensating_invariant/distribution_confirm_then_reverse_conserves_rmd_satisfaction
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(
        full_name="SaraCompanion",
        date_of_birth="1953-03-03",
        tax_id_last4="1910",
        filing_status="SINGLE",
    )
    trad = create_account(owner["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )
    sched = create_rmd_schedule(owner["id"], 2026)
    required = sched["required_amount_cents"]
    refreshed_v1 = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=owner["id"],
        amount_cents=required,
        distribution_reason="RMD",
        tax_year=2026,
    )
    confirm_distribution(pending["id"], owner["id"], refreshed_v1["version"])
    mid_acct = get_account(trad["id"], make_account_owner_headers(owner["id"]))
    assert mid_acct["cash_balance_cents"] == 700_000 - required

    refreshed_v2 = get_account(trad["id"], TEST_USERS["plan_admin_headers"])
    rev_res = api.reverse_distribution(
        pending["id"],
        {"expected_account_version": refreshed_v2["version"]},
        TEST_USERS["plan_admin_headers"],
    )
    reversed_data = validate_success(rev_res, expected_status=200)
    assert reversed_data["status"] == "REVERSED"

    after_acct = get_account(trad["id"], TEST_USERS["plan_admin_headers"])
    assert after_acct["cash_balance_cents"] == 700_000, (
        f"reverse must restore cash_balance_cents to pre-confirm value 700000, "
        f"got {after_acct['cash_balance_cents']}"
    )
