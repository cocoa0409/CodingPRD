"""RMD schedule math, age-73 boundary, SECURE 10-year rule, distribution
preconditions (PRD §3.4, §3.6, §3.7)."""
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
    add_active_beneficiary,
    create_rmd_schedule,
    create_pending_distribution,
    confirm_distribution,
    declare_deceased,
    get_account,
    get_owner,
    setup_inherited_traditional_with_secure_deadline,
    make_account_owner_headers,
)


# =============================================================================
# Difficulty Rule 1 instance #2 — RMD variant divergence (living vs SECURE)
# =============================================================================


class TestRMDVariantDivergence:
    """Same owner and same TRADITIONAL balance produce different
    required_amount_cents under the living-owner Uniform Lifetime variant
    versus the SECURE 10-year-pace variant once the owner is declared deceased."""

    def test_living_owner_uses_uniform_lifetime_divisor(self, api):
        """PRD §3.7: "For a living owner aged at least seventy-three at
        year-end, the system aggregates `cash_balance_cents` across the
        owner's Traditional accounts whose `status` is in the set `ACTIVE` or
        `FROZEN`..."
        PRD §3.7: "The divisor table, stored in basis-point form (the integer
        2660 represents the decimal divisor 26.60), runs as follows: age 73 →
        2660..."
        PRD §3.7: "The required amount in cents is computed sum-then-divide:
        the aggregated total balance in cents is multiplied by 100, then
        floor-divided by the divisor in basis-point form, yielding an
        integer-cent result."

        Concretely: balance 700000, age 73 → 700000 * 100 // 2660 = 26315.

        Design: Difficulty/dual_variant_calc/rmd_amount_variant_divergence_on_account_owner
        """
        set_clock("2026-06-01T00:00:00Z")
        bob = create_owner(
            full_name="Bob",
            date_of_birth="1953-01-15",
            tax_id_last4="5678",
            filing_status="SINGLE",
            modified_agi_cents=5_000_000,
        )
        trad = create_account(bob["id"], "TRADITIONAL")
        fund_account_with_contribution(
            account_id=trad["id"],
            owner_id=bob["id"],
            tax_year=2026,
            amount_cents=700_000,
            contribution_kind="PRETAX",
        )

        sched = create_rmd_schedule(bob["id"], 2026)
        assert sched["required_amount_cents"] == 26_315, (
            f"living-owner Uniform Lifetime divisor 26.60 on balance 700000 "
            f"must yield 26315, got {sched['required_amount_cents']}"
        )

    def test_deceased_owner_secure_year_one_uses_even_allocation(self, api):
        """PRD §3.7: "For a deceased owner whose surviving designated
        beneficiary's `relationship` is `NON_ELIGIBLE_INDIVIDUAL`, the Uniform
        Lifetime math is replaced entirely by an even allocation under the
        SECURE Act ten-year pace. The total inherited balance is taken as the
        sum of `cash_balance_cents` across all inherited Traditional accounts
        attached to that beneficiary. The years remaining are computed as the
        difference between `secure_deadline_at` and the system clock's
        `current_utc`, divided by 365 days and rounded up to the next whole
        year. Each year's `required_amount_cents` is the total inherited
        balance integer-divided by the years remaining."
        PRD §3.6: "for every inherited designation whose `relationship` is
        `NON_ELIGIBLE_INDIVIDUAL`, `secure_deadline_at` is computed as the
        owner's `deceased_at` plus ten years..."

        Year 1: secure_deadline_at = deceased_at (2026-06-01T12:00:00Z) + 10
        years = 2036-06-01T12:00:00Z. current_utc = 2026-06-01T00:00:00Z. The
        gap is 3653.5 days (10 calendar years span 3653 days due to 3 leap
        days, plus the 12-hour offset). 3653.5 / 365 = 10.009..., rounded UP to
        the next whole year per PRD = 11 years remaining; required =
        700000 // 11 = 63636.

        Design: Difficulty/dual_variant_calc/rmd_amount_variant_divergence_on_account_owner
        """
        owner, account, beneficiary = (
            setup_inherited_traditional_with_secure_deadline(
                iso8601_alive="2026-06-01T00:00:00Z",
                deceased_at="2026-06-01T12:00:00Z",
                date_of_birth="1953-01-15",
                cash_cents=700_000,
                funding_tax_year=2026,
                full_name="Bob",
                tax_id_last4="5678",
            )
        )

        sched = create_rmd_schedule(owner["id"], 2026)
        assert sched["required_amount_cents"] == 63_636, (
            f"SECURE year-1 even-allocation on 700000 with 11 years remaining "
            f"(3653.5-day gap / 365, rounded up) must yield 63636, got "
            f"{sched['required_amount_cents']}"
        )


# =============================================================================
# Difficulty Rule 6 instance #2 — Age-73 boundary on RMD schedule create
# =============================================================================


class TestRMDAgeBoundary:
    """RMD obligation lands the year the owner reaches 73 by year-end."""

    def test_age_72_at_eoy_produces_zero_required_amount(self, api):
        """PRD §3.7: "For a living owner whose age at the end of `tax_year`
        (the integer year difference between December 31 of `tax_year` and
        `date_of_birth`) is below seventy-three, the requirement is zero."

        Lena DOB 1954-01-15: 2026 - 1954 = 72. age-at-EOY = 72 → required = 0.

        Design: Difficulty/boundary_precision_check/rmd_age_threshold_seventy_three_boundary_on_rmd_schedule_create
        """
        set_clock("2026-06-01T00:00:00Z")
        lena = create_owner(
            full_name="Lena",
            date_of_birth="1954-01-15",
            tax_id_last4="1212",
            filing_status="SINGLE",
        )
        trad = create_account(lena["id"], "TRADITIONAL")
        fund_account_with_contribution(
            account_id=trad["id"],
            owner_id=lena["id"],
            tax_year=2026,
            amount_cents=700_000,
            contribution_kind="PRETAX",
        )
        sched = create_rmd_schedule(lena["id"], 2026)
        assert sched["required_amount_cents"] == 0, (
            f"age 72 at EOY must produce required_amount_cents=0, "
            f"got {sched['required_amount_cents']}"
        )

    def test_age_73_at_eoy_produces_uniform_lifetime_amount(self, api):
        """PRD §3.7: "For a living owner aged at least seventy-three at
        year-end, the system aggregates `cash_balance_cents` across the
        owner's Traditional accounts..."
        PRD §3.7: "The divisor table, stored in basis-point form (the integer
        2660 represents the decimal divisor 26.60), runs as follows: age 73 →
        2660..."

        Mona DOB 1953-01-15: 2026 - 1953 = 73. With cash 700000 →
        700000 * 100 // 2660 = 26315.

        Design: Difficulty/boundary_precision_check/rmd_age_threshold_seventy_three_boundary_on_rmd_schedule_create
        """
        set_clock("2026-06-01T00:00:00Z")
        mona = create_owner(
            full_name="Mona",
            date_of_birth="1953-01-15",
            tax_id_last4="1313",
            filing_status="SINGLE",
        )
        trad = create_account(mona["id"], "TRADITIONAL")
        fund_account_with_contribution(
            account_id=trad["id"],
            owner_id=mona["id"],
            tax_year=2026,
            amount_cents=700_000,
            contribution_kind="PRETAX",
        )
        sched = create_rmd_schedule(mona["id"], 2026)
        assert sched["required_amount_cents"] == 26_315, (
            f"age 73 EOY with cash 700000 must yield required=26315, "
            f"got {sched['required_amount_cents']}"
        )


# =============================================================================
# Difficulty Rule 7 instance #2 — RMD distribution requires open RMDSchedule
# =============================================================================


def test_rmd_distribution_confirm_without_open_schedule_rejected(api):
    """PRD §3.4: "Second, if `distribution_reason` is `RMD` there must be an
    `OPEN` (or, on a late-cure, a `DELINQUENT`) `RMDSchedule` for this owner
    and this `tax_year`; the schedule is what the satisfied amount accumulates
    against."
    PRD §2.6: "Third, state: for action endpoints the target entity must be in
    the from-state declared by the relevant transition, with rejection code
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/rmd_distribution_confirm_requires_open_rmd_schedule
    """
    set_clock("2026-06-01T00:00:00Z")
    olive = create_owner(
        full_name="Olive",
        date_of_birth="1953-06-06",
        tax_id_last4="1515",
        filing_status="SINGLE",
    )
    trad = create_account(olive["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=olive["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )

    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=olive["id"],
        amount_cents=26_315,
        distribution_reason="RMD",
        tax_year=2026,
    )
    refreshed = get_account(trad["id"], make_account_owner_headers(olive["id"]))
    res = api.confirm_distribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(olive["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Difficulty Rule 8 instance #2 — SECURE 10-year deadline closed-endpoint cutoff
# =============================================================================


def test_secure_deadline_passed_blocks_inherited_distribution_with_residual(api):
    """PRD §3.4: "Third, on an `INHERITED` Traditional account whose active
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
            full_name="Quinn",
            tax_id_last4="1717",
        )
    )

    # Advance the clock past the secure_deadline_at (2036-06-01 + 10y = 2036-06-01).
    set_clock("2036-06-02T00:00:00Z")
    refreshed = get_account(account["id"], TEST_USERS["plan_admin_headers"])

    pending = create_pending_distribution(
        account_id=account["id"],
        owner_id=owner["id"],
        amount_cents=10_000,  # leaves 690000 past the deadline
        distribution_reason="INHERITED",
        tax_year=2036,
    )
    res = api.confirm_distribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(owner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SECURE_DEADLINE_PASSED.value)


# =============================================================================
# Difficulty Rule 4 instance #1 — declare-deceased depth-≥4 cascade
# =============================================================================


def test_declare_deceased_cascades_through_account_beneficiary_and_secure_deadline(
    api,
):
    """PRD §3.6: "Every `IRAAccount` belonging to this owner that is currently
    in `ACTIVE` or `FROZEN` transitions to `INHERITED`; every
    `BeneficiaryDesignation` currently in `ACTIVE` on those accounts
    transitions to `INHERITED`; for every inherited designation whose
    `relationship` is `NON_ELIGIBLE_INDIVIDUAL`, `secure_deadline_at` is
    computed as the owner's `deceased_at` plus ten years..."

    Design: Difficulty/transitive_cascade/declare_deceased_depth4_cascade_through_inherited_beneficiary_rmd
    """
    owner, account, beneficiary = (
        setup_inherited_traditional_with_secure_deadline(
            iso8601_alive="2026-06-01T00:00:00Z",
            deceased_at="2026-06-01T12:00:00Z",
            date_of_birth="1953-04-04",
            cash_cents=700_000,
            funding_tax_year=2026,
            full_name="Gina",
            tax_id_last4="5555",
        )
    )
    # Account cascaded to INHERITED.
    assert account["status"] == "INHERITED", (
        f"declare-deceased must cascade ACTIVE -> INHERITED on the owner's "
        f"account, got {account['status']!r}"
    )
    # Beneficiary cascaded to INHERITED.
    assert beneficiary["status"] == "INHERITED", (
        f"declare-deceased must cascade ACTIVE -> INHERITED on the active "
        f"beneficiary, got {beneficiary['status']!r}"
    )
    # secure_deadline_at = deceased_at + 10y = 2036-06-01T12:00:00Z.
    deadline = beneficiary.get("secure_deadline_at") or ""
    assert deadline.startswith("2036-06-01T12:00:00"), (
        f"secure_deadline_at must be deceased_at + 10 years (2036-06-01T12:00:00...), "
        f"got {deadline!r}"
    )


# =============================================================================
# Difficulty Rule 4 instance #2 — distribution confirm depth-≥3 RMD cascade
# =============================================================================


def test_rmd_distribution_confirm_satisfies_schedule_and_updates_posture(api):
    """PRD §3.4: "If `distribution_reason` is `RMD` the matching
    `RMDSchedule`'s `satisfied_amount_cents` increases by `amount_cents`; if
    the post-increase `satisfied_amount_cents` is greater than or equal to the
    schedule's `required_amount_cents`, the schedule transitions from `OPEN`
    to `SATISFIED`, or from `DELINQUENT` to `SATISFIED` if the confirm is a
    late cure."
    PRD §3.4: "`AccountOwner.rmd_posture` is then recomputed across all owned
    Traditional accounts to one of `NOT_REQUIRED`, `REQUIRED_PENDING`,
    `REQUIRED_MET`, or `REQUIRED_DELINQUENT`."

    Design: Difficulty/transitive_cascade/distribution_confirm_rmd_satisfaction_depth3_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    henry = create_owner(
        full_name="Henry",
        date_of_birth="1953-05-05",
        tax_id_last4="6666",
        filing_status="SINGLE",
    )
    trad = create_account(henry["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=henry["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )
    sched = create_rmd_schedule(henry["id"], 2026)
    required = sched["required_amount_cents"]
    assert required == 26_315

    refreshed = get_account(trad["id"], make_account_owner_headers(henry["id"]))
    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=henry["id"],
        amount_cents=required,
        distribution_reason="RMD",
        tax_year=2026,
    )
    confirmed = confirm_distribution(pending["id"], henry["id"], refreshed["version"])
    assert confirmed["status"] == "CONFIRMED"

    from test_helpers import get_rmd_schedule

    sched_after = get_rmd_schedule(sched["id"])
    assert sched_after["status"] == "SATISFIED", (
        f"schedule must transition OPEN -> SATISFIED, got {sched_after['status']!r}"
    )
    assert sched_after["satisfied_amount_cents"] == required

    owner_after = get_owner(henry["id"])
    assert owner_after["rmd_posture"] == "REQUIRED_MET", (
        f"rmd_posture must be REQUIRED_MET after the schedule is SATISFIED, "
        f"got {owner_after['rmd_posture']!r}"
    )

    acct_after = get_account(trad["id"], make_account_owner_headers(henry["id"]))
    assert acct_after["cash_balance_cents"] == 700_000 - required


# =============================================================================
# Corner: beneficiary shares must sum to 10000 on activate
# =============================================================================


def test_beneficiary_activate_with_share_sum_below_10000_rejected(api):
    """PRD §3.6: "Activation moves the designation from `PENDING` to `ACTIVE`
    and is gated on a hard arithmetic check: the sum of `percentage_bps`
    across all designations on this account whose `status` becomes `ACTIVE`
    after the activation (the newly activated row included with the rows
    already in `ACTIVE`) must equal exactly 10000; otherwise the activation
    is rejected with `ERR_BENEFICIARY_SHARES_INVALID`."

    Design: Corner/validations/beneficiary_shares_sum_must_equal_10000_on_activate
    """
    set_clock("2026-06-01T00:00:00Z")
    xena = create_owner(
        full_name="Xena",
        date_of_birth="1981-04-04",
        tax_id_last4="2424",
        filing_status="SINGLE",
    )
    trad = create_account(xena["id"], "TRADITIONAL")

    from test_helpers import create_beneficiary

    designation = create_beneficiary(
        account_id=trad["id"],
        owner_id=xena["id"],
        beneficiary_full_name="Half Heir",
        relationship="SPOUSE",
        percentage_bps=5000,
    )

    res = api.activate_beneficiary_designation(
        designation["id"], make_account_owner_headers(xena["id"])
    )
    validate_error(res, ApiErrorId.ERR_BENEFICIARY_SHARES_INVALID.value)


# =============================================================================
# Corner: withholding exceeds amount returns ERR_INSUFFICIENT_BALANCE
# =============================================================================


def test_distribution_withholding_exceeds_amount_returns_insufficient_balance(api):
    """PRD §3.4: "First, `amount_cents` must not exceed `cash_balance_cents`
    and `federal_withholding_cents` must not exceed `amount_cents`; either
    violation yields `ERR_INSUFFICIENT_BALANCE`."

    Design: Corner/validations/distribution_withholding_exceeds_amount_returns_insufficient_balance
    """
    set_clock("2026-06-01T00:00:00Z")
    brian = create_owner(
        full_name="Brian",
        date_of_birth="1981-08-08",
        tax_id_last4="2828",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(brian["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=brian["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )
    refreshed = get_account(trad["id"], make_account_owner_headers(brian["id"]))

    pending = create_pending_distribution(
        account_id=trad["id"],
        owner_id=brian["id"],
        amount_cents=10_000,
        distribution_reason="NORMAL",
        tax_year=2026,
        federal_withholding_cents=15_000,
    )
    res = api.confirm_distribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(brian["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)
