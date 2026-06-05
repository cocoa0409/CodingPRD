"""Contribution cap math, Roth phase-out, catch-up, and tax-year-window rules
(PRD §3.3, §3.7)."""
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
    get_account,
    advance_year_rollover,
    make_account_owner_headers,
)


# =============================================================================
# Difficulty Rule 2 instance #1 — Roth eligibility three-input phase-out with
# floor-to-1000
# =============================================================================


def test_roth_eligibility_phaseout_caps_at_floored_allowance(api):
    """PRD §3.3: "Otherwise the system computes a linear in-band reduction:
    take the difference between `modified_agi_cents` and the floor, multiply
    by the headroom in cents, then floor-divide by the width of the band
    (ceiling minus floor); subtract that reduction from the headroom; finally,
    floor the resulting allowance to the nearest multiple of 1,000 cents (ten
    dollars) by integer-dividing by 1,000 and re-multiplying by 1,000."
    PRD §3.3: "the sum of the account's existing `ytd_contribution_cents` and
    the contribution's `amount_cents` must not exceed the per-year contribution
    limit for this owner, account type, and tax year (see below); breach yields
    `ERR_CONTRIBUTION_CAP_EXCEEDED`."

    Concretely for SINGLE 2026, base+catch-up at age 45 = 750000, AGI 16000000
    sits in band [15400000, 16900000]. Reduction = 750000 * (16000000-15400000)
    // (16900000-15400000) = 750000 * 600000 // 1500000 = 300000. Allowed =
    450000, already a multiple of 1000. After confirming a 450000 ROTH
    contribution, headroom is exhausted; the next 1-cent confirm must breach
    the cap.

    Design: Difficulty/combinatorial_formula/roth_eligibility_three_input_phaseout_with_floor_to_1000
    """
    set_clock("2026-06-01T00:00:00Z")
    carol = create_owner(
        full_name="Carol",
        date_of_birth="1981-04-04",
        tax_id_last4="9999",
        filing_status="SINGLE",
        modified_agi_cents=16_000_000,
    )
    carol_roth = create_account(carol["id"], "ROTH")
    v0 = carol_roth["version"]

    # First Roth confirmation at the exact phase-out allowance: 450000 must pass.
    fund_account_with_contribution(
        account_id=carol_roth["id"],
        owner_id=carol["id"],
        tax_year=2026,
        amount_cents=450_000,
        contribution_kind="ROTH",
    )
    refreshed = get_account(carol_roth["id"], make_account_owner_headers(carol["id"]))
    assert refreshed["ytd_contribution_cents"] == 450_000

    # Second Roth contribution of 1 cent — confirming would push ytd to 450001 > 450000.
    pending = create_pending_contribution(
        account_id=carol_roth["id"],
        owner_id=carol["id"],
        tax_year=2026,
        amount_cents=1,
        contribution_kind="ROTH",
    )
    res = api.confirm_contribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(carol["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


# =============================================================================
# Difficulty Rule 6 instance #1 — Contribution cap boundary (<= passes, > fails)
# =============================================================================


class TestContributionCapBoundary:
    """The contribution-cap check is inclusive: ytd + amount <= cap passes;
    ytd + amount > cap (one cent over) fails."""

    def test_contribution_at_exact_cap_passes(self, api):
        """PRD §3.3: "the sum of the account's existing
        `ytd_contribution_cents` and the contribution's `amount_cents` must
        not exceed the per-year contribution limit for this owner, account
        type, and tax year (see below); breach yields
        `ERR_CONTRIBUTION_CAP_EXCEEDED`."
        PRD §3.3: "A base limit applies to every owner: 700,000 cents (seven
        thousand dollars) for tax years 2024 and 2025, and 750,000 cents
        (seven thousand five hundred dollars) for tax year 2026."

        Design: Difficulty/boundary_precision_check/contribution_cap_boundary_at_exact_cap_passes_one_cent_over_fails
        """
        set_clock("2026-06-01T00:00:00Z")
        karl = create_owner(
            full_name="Karl",
            date_of_birth="1981-10-10",
            tax_id_last4="1010",
            filing_status="SINGLE",
            modified_agi_cents=12_000_000,
        )
        karl_trad = create_account(karl["id"], "TRADITIONAL")

        pending = create_pending_contribution(
            account_id=karl_trad["id"],
            owner_id=karl["id"],
            tax_year=2026,
            amount_cents=750_000,
            contribution_kind="PRETAX",
        )
        confirmed = confirm_contribution(pending["id"], karl["id"], karl_trad["version"])
        assert confirmed["status"] == "CONFIRMED", (
            f"exact-cap contribution must pass, got status {confirmed['status']!r}"
        )

        refreshed = get_account(karl_trad["id"], make_account_owner_headers(karl["id"]))
        assert refreshed["ytd_contribution_cents"] == 750_000

    def test_contribution_one_cent_over_cap_fails(self, api):
        """PRD §3.3: "the sum of the account's existing
        `ytd_contribution_cents` and the contribution's `amount_cents` must
        not exceed the per-year contribution limit for this owner, account
        type, and tax year (see below); breach yields
        `ERR_CONTRIBUTION_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/contribution_cap_boundary_at_exact_cap_passes_one_cent_over_fails
        """
        set_clock("2026-06-01T00:00:00Z")
        karl = create_owner(
            full_name="Karl",
            date_of_birth="1981-10-10",
            tax_id_last4="1010",
            filing_status="SINGLE",
            modified_agi_cents=12_000_000,
        )
        karl_trad = create_account(karl["id"], "TRADITIONAL")
        fund_account_with_contribution(
            account_id=karl_trad["id"],
            owner_id=karl["id"],
            tax_year=2026,
            amount_cents=750_000,
            contribution_kind="PRETAX",
        )

        # ytd = 750000 (cap for SINGLE 2026 no catch-up). One-cent more crosses.
        refreshed = get_account(karl_trad["id"], make_account_owner_headers(karl["id"]))
        pending = create_pending_contribution(
            account_id=karl_trad["id"],
            owner_id=karl["id"],
            tax_year=2026,
            amount_cents=1,
            contribution_kind="PRETAX",
        )
        res = api.confirm_contribution(
            pending["id"],
            {"expected_account_version": refreshed["version"]},
            make_account_owner_headers(karl["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


# =============================================================================
# Difficulty Rule 8 instance #1 — Aggregate capacity within the tax-year window
# =============================================================================


def test_aggregate_contributions_within_year_cannot_exceed_cap(api):
    """PRD §3.3: "the sum of the account's existing `ytd_contribution_cents`
    and the contribution's `amount_cents` must not exceed the per-year
    contribution limit for this owner, account type, and tax year (see below);
    breach yields `ERR_CONTRIBUTION_CAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/contribution_tax_year_window_aggregate_capacity_overlap_on_contribution
    """
    set_clock("2026-06-01T00:00:00Z")
    peter = create_owner(
        full_name="Peter",
        date_of_birth="1981-12-12",
        tax_id_last4="1616",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    peter_trad = create_account(peter["id"], "TRADITIONAL")
    fund_account_with_contribution(
        account_id=peter_trad["id"],
        owner_id=peter["id"],
        tax_year=2026,
        amount_cents=700_000,
        contribution_kind="PRETAX",
    )
    refreshed = get_account(peter_trad["id"], make_account_owner_headers(peter["id"]))
    assert refreshed["ytd_contribution_cents"] == 700_000

    # Second contribution: 60000 would push ytd to 760000 > 750000 cap.
    pending = create_pending_contribution(
        account_id=peter_trad["id"],
        owner_id=peter["id"],
        tax_year=2026,
        amount_cents=60_000,
        contribution_kind="PRETAX",
    )
    res = api.confirm_contribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(peter["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


# =============================================================================
# Corner: catch-up at age 50 exact (correct_result)
# =============================================================================


class TestCatchUpAtAge50:
    """Catch-up adds 110000 cents in 2026 to owners aged at least 50 by EOY."""

    def test_age_50_at_eoy_gets_catch_up(self, api):
        """PRD §3.3: "A catch-up addition is granted when the owner is at least
        fifty years old at year-end: 100,000 cents (one thousand dollars) for
        tax years 2024 and 2025, and 110,000 cents (eleven hundred dollars)
        for tax year 2026; an owner younger than fifty receives no catch-up."
        PRD §3.3: "First, the owner's age at the end of the tax year is taken
        as the integer year difference between December 31 of the `tax_year`
        and `date_of_birth`."

        Design: Corner/calculations/catch_up_contribution_limit_kicks_in_at_age_50_exact
        """
        set_clock("2026-06-01T00:00:00Z")
        tom = create_owner(
            full_name="Tom",
            date_of_birth="1976-12-31",  # age-at-EOY-2026 = 50
            tax_id_last4="2020",
            filing_status="SINGLE",
            modified_agi_cents=5_000_000,
        )
        trad = create_account(tom["id"], "TRADITIONAL")
        pending = create_pending_contribution(
            account_id=trad["id"],
            owner_id=tom["id"],
            tax_year=2026,
            amount_cents=860_000,  # base 750000 + catch-up 110000
            contribution_kind="PRETAX",
        )
        confirmed = confirm_contribution(pending["id"], tom["id"], trad["version"])
        assert confirmed["status"] == "CONFIRMED", (
            f"age-50 owner must receive catch-up; expected CONFIRMED, got "
            f"{confirmed['status']!r}"
        )

    def test_age_49_at_eoy_receives_no_catch_up(self, api):
        """PRD §3.3: "an owner younger than fifty receives no catch-up."
        PRD §3.3: "the sum of the account's existing `ytd_contribution_cents`
        and the contribution's `amount_cents` must not exceed the per-year
        contribution limit for this owner, account type, and tax year (see
        below); breach yields `ERR_CONTRIBUTION_CAP_EXCEEDED`."

        Design: Corner/calculations/catch_up_contribution_limit_kicks_in_at_age_50_exact
        """
        set_clock("2026-06-01T00:00:00Z")
        una = create_owner(
            full_name="Una",
            date_of_birth="1977-01-01",  # age-at-EOY-2026 = 49
            tax_id_last4="2121",
            filing_status="SINGLE",
            modified_agi_cents=5_000_000,
        )
        trad = create_account(una["id"], "TRADITIONAL")
        pending = create_pending_contribution(
            account_id=trad["id"],
            owner_id=una["id"],
            tax_year=2026,
            amount_cents=750_001,  # one cent over the no-catch-up cap
            contribution_kind="PRETAX",
        )
        res = api.confirm_contribution(
            pending["id"],
            {"expected_account_version": trad["version"]},
            make_account_owner_headers(una["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


# =============================================================================
# Corner: Roth phase-out at ceiling returns zero eligibility
# =============================================================================


def test_roth_phaseout_at_ceiling_returns_zero_eligibility(api):
    """PRD §3.3: "If `modified_agi_cents` is greater than or equal to the
    ceiling, the allowance is zero — no Roth contribution may confirm."
    PRD §3.3: "if the phase-out returns zero (the owner's modified AGI is at
    or above the ceiling for their filing status), the confirm is rejected
    with `ERR_CONTRIBUTION_CAP_EXCEEDED` against an effective cap of zero."

    Design: Corner/calculations/roth_phaseout_at_ceiling_returns_zero_eligibility
    """
    set_clock("2026-06-01T00:00:00Z")
    victor = create_owner(
        full_name="Victor",
        date_of_birth="1981-02-02",
        tax_id_last4="2222",
        filing_status="SINGLE",
        modified_agi_cents=16_900_000,  # exactly ceiling for SINGLE 2026
    )
    roth = create_account(victor["id"], "ROTH")

    pending = create_pending_contribution(
        account_id=roth["id"],
        owner_id=victor["id"],
        tax_year=2026,
        amount_cents=1,
        contribution_kind="ROTH",
    )
    res = api.confirm_contribution(
        pending["id"],
        {"expected_account_version": roth["version"]},
        make_account_owner_headers(victor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONTRIBUTION_CAP_EXCEEDED.value)


# =============================================================================
# Corner: tax-year-closed after ops rollover
# =============================================================================


def test_contribution_confirm_after_year_rollover_rejected_tax_year_closed(api):
    """PRD §3.3: "Second, the contribution's `tax_year` must equal the
    account's `tax_year_marker` at the moment of confirmation; a contribution
    created before a year-rollover and confirmed after it is rejected with
    `ERR_TAX_YEAR_CLOSED`."

    Design: Corner/validations/tax_year_closed_after_rollover_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    anya = create_owner(
        full_name="Anya",
        date_of_birth="1981-07-07",
        tax_id_last4="2727",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(anya["id"], "TRADITIONAL")
    pending = create_pending_contribution(
        account_id=trad["id"],
        owner_id=anya["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="PRETAX",
    )

    # Advance the clock and run the year-rollover; account.tax_year_marker -> 2027.
    set_clock("2027-01-15T00:00:00Z")
    advance_year_rollover(2027)

    refreshed = get_account(trad["id"], make_account_owner_headers(anya["id"]))
    res = api.confirm_contribution(
        pending["id"],
        {"expected_account_version": refreshed["version"]},
        make_account_owner_headers(anya["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TAX_YEAR_CLOSED.value)
