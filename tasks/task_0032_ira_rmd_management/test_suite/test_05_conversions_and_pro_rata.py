"""Backdoor Roth conversions: pro-rata math, variant divergence, preconditions
(PRD §3.5)."""
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
    initiate_conversion,
    complete_conversion,
    get_account,
    advance_year_rollover,
    make_account_owner_headers,
)


# =============================================================================
# Difficulty Rule 1 instance #1 — single vs aggregated basis variant divergence
# =============================================================================


def test_pro_rata_variant_divergence_single_vs_aggregated(api):
    """PRD §3.5: "In the single-account default (the request omits
    `aggregate_basis` or sets it to false), the split runs against the source
    account's own bases only."
    PRD §3.5: "When the owner sets `aggregate_basis` to true and has two or
    more Traditional accounts, the split is recomputed against the owner's
    aggregated basis: the pretax and aftertax inputs to the same formula are
    replaced by the sums of `pretax_basis_cents` and `aftertax_basis_cents`
    across every Traditional account belonging to this owner, and the formula
    then runs identically."
    PRD §3.5: "Otherwise the nontaxable portion is gross multiplied by
    aftertax, floor-divided by the sum of pretax and aftertax; the taxable
    portion is gross minus the nontaxable portion."

    Design: Difficulty/dual_variant_calc/backdoor_roth_pro_rata_variant_divergence_on_conversion
    """
    set_clock("2026-06-01T00:00:00Z")
    alice = create_owner(
        full_name="Alice",
        date_of_birth="1981-03-10",
        tax_id_last4="1234",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    sibling = create_account(alice["id"], "TRADITIONAL")
    source_a = create_account(alice["id"], "TRADITIONAL")
    source_b = create_account(alice["id"], "TRADITIONAL")
    roth = create_account(alice["id"], "ROTH")

    # Sibling holds pretax 600000.
    fund_account_with_contribution(
        account_id=sibling["id"],
        owner_id=alice["id"],
        tax_year=2026,
        amount_cents=600_000,
        contribution_kind="PRETAX",
    )
    # source_a and source_b each hold aftertax 200000.
    fund_account_with_contribution(
        account_id=source_a["id"],
        owner_id=alice["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="AFTERTAX",
    )
    fund_account_with_contribution(
        account_id=source_b["id"],
        owner_id=alice["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="AFTERTAX",
    )

    # Conversion A on source_a — default (single-account) variant.
    refreshed_a = get_account(source_a["id"], make_account_owner_headers(alice["id"]))
    conv_a = initiate_conversion(
        source_account_id=source_a["id"],
        target_account_id=roth["id"],
        owner_id=alice["id"],
        gross_amount_cents=200_000,
    )
    refreshed_a_after_init = get_account(
        source_a["id"], make_account_owner_headers(alice["id"])
    )
    conv_a_completed = complete_conversion(
        conv_a["id"], alice["id"], refreshed_a_after_init["version"]
    )
    # source_a has pretax=0, aftertax=200000 → nontax = 200000*200000//200000 = 200000.
    assert conv_a_completed["taxable_amount_cents"] == 0, (
        f"single-account variant on aftertax-only source must be fully nontaxable, "
        f"got taxable={conv_a_completed['taxable_amount_cents']}"
    )
    assert conv_a_completed["nontaxable_amount_cents"] == 200_000, (
        f"single-account variant nontaxable must be 200000, "
        f"got {conv_a_completed['nontaxable_amount_cents']}"
    )

    # Conversion B on source_b — aggregate_basis=true.
    # At this point: sibling pretax=600000, source_a pretax=0/aftertax=0 (drained),
    # source_b pretax=0/aftertax=200000.
    # Aggregated pretax = 600000+0+0 = 600000; aggregated aftertax = 0+0+200000 = 200000.
    # nontax = 200000*200000//(600000+200000) = 40000000000//800000 = 50000.
    # taxable = 200000 - 50000 = 150000.
    conv_b = initiate_conversion(
        source_account_id=source_b["id"],
        target_account_id=roth["id"],
        owner_id=alice["id"],
        gross_amount_cents=200_000,
        aggregate_basis=True,
    )
    refreshed_b_after_init = get_account(
        source_b["id"], make_account_owner_headers(alice["id"])
    )
    conv_b_completed = complete_conversion(
        conv_b["id"], alice["id"], refreshed_b_after_init["version"]
    )
    assert conv_b_completed["taxable_amount_cents"] == 150_000, (
        f"aggregated variant taxable must be 150000, "
        f"got {conv_b_completed['taxable_amount_cents']}"
    )
    assert conv_b_completed["nontaxable_amount_cents"] == 50_000, (
        f"aggregated variant nontaxable must be 50000, "
        f"got {conv_b_completed['nontaxable_amount_cents']}"
    )
    assert (
        conv_a_completed["taxable_amount_cents"]
        != conv_b_completed["taxable_amount_cents"]
    ), "single vs aggregated variants must produce different taxable splits"


# =============================================================================
# Difficulty Rule 2 instance #2 — sum-then-divide rounding order
# =============================================================================


def test_pro_rata_nested_rounding_order_sum_then_divide(api):
    """PRD §3.5: "Otherwise the nontaxable portion is gross multiplied by
    aftertax, floor-divided by the sum of pretax and aftertax; the taxable
    portion is gross minus the nontaxable portion. The floor at the final
    divide truncates toward zero, and any cent of remainder lands on the
    taxable side. There is no per-line rounding earlier in the chain."

    With gross=200000, pretax=500000, aftertax=300000: the prescribed order
    yields nontax = 200000*300000 // 800000 = 75000; taxable = 125000.

    Design: Difficulty/combinatorial_formula/backdoor_roth_pro_rata_nested_rounding_order_on_conversion
    """
    set_clock("2026-06-01T00:00:00Z")
    dave = create_owner(
        full_name="Dave",
        date_of_birth="1981-07-22",
        tax_id_last4="2222",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(dave["id"], "TRADITIONAL")
    roth = create_account(dave["id"], "ROTH")

    # Year 2026: fund pretax 500000 + aftertax 100000.
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=dave["id"],
        tax_year=2026,
        amount_cents=500_000,
        contribution_kind="PRETAX",
    )
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=dave["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="AFTERTAX",
    )

    # Roll year to 2027 to reset ytd.
    advance_year_rollover(2027)
    set_clock("2027-01-15T00:00:00Z")

    # Year 2027: fund aftertax 200000.
    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=dave["id"],
        tax_year=2027,
        amount_cents=200_000,
        contribution_kind="AFTERTAX",
    )

    refreshed = get_account(trad["id"], make_account_owner_headers(dave["id"]))
    assert refreshed["pretax_basis_cents"] == 500_000
    assert refreshed["aftertax_basis_cents"] == 300_000
    assert refreshed["cash_balance_cents"] == 800_000

    conv = initiate_conversion(
        source_account_id=trad["id"],
        target_account_id=roth["id"],
        owner_id=dave["id"],
        gross_amount_cents=200_000,
    )
    refreshed_after_init = get_account(trad["id"], make_account_owner_headers(dave["id"]))
    completed = complete_conversion(
        conv["id"], dave["id"], refreshed_after_init["version"]
    )

    # nontax = 200000 * 300000 // 800000 = 75000; taxable = 125000.
    assert completed["taxable_amount_cents"] == 125_000, (
        f"sum-then-divide taxable must be 125000, got {completed['taxable_amount_cents']}"
    )
    assert completed["nontaxable_amount_cents"] == 75_000, (
        f"sum-then-divide nontaxable must be 75000, "
        f"got {completed['nontaxable_amount_cents']}"
    )
    final_acct = get_account(trad["id"], make_account_owner_headers(dave["id"]))
    assert final_acct["cash_balance_cents"] == 600_000, (
        f"source cash after 200000 conversion must be 600000, "
        f"got {final_acct['cash_balance_cents']}"
    )


# =============================================================================
# Difficulty Rule 7 instance #1 — Conversion complete requires target ROTH ACTIVE
# =============================================================================


def test_conversion_complete_fails_when_target_roth_frozen(api):
    """PRD §3.5: "Completion (initiated to `COMPLETED`) requires the target
    Roth account to be `ACTIVE` and consumes `expected_source_account_version`."
    PRD §2.6: "Third, state: for action endpoints the target entity must be in
    the from-state declared by the relevant transition, with rejection code
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/conversion_completes_only_when_target_roth_account_active
    """
    set_clock("2026-06-01T00:00:00Z")
    noah = create_owner(
        full_name="Noah",
        date_of_birth="1981-11-11",
        tax_id_last4="1414",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(noah["id"], "TRADITIONAL")
    roth = create_account(noah["id"], "ROTH")
    roth_v0 = roth["version"]

    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=noah["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="AFTERTAX",
    )

    conv = initiate_conversion(
        source_account_id=trad["id"],
        target_account_id=roth["id"],
        owner_id=noah["id"],
        gross_amount_cents=200_000,
    )

    # Freeze the target ROTH so its status != ACTIVE.
    freeze_res = api.freeze_account(
        roth["id"],
        {"expected_account_version": roth_v0},
        TEST_USERS["plan_admin_headers"],
    )
    validate_success(freeze_res, expected_status=200)

    refreshed_trad = get_account(trad["id"], make_account_owner_headers(noah["id"]))
    res = api.complete_conversion(
        conv["id"],
        {"expected_source_account_version": refreshed_trad["version"]},
        make_account_owner_headers(noah["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# =============================================================================
# Corner: pro_rata_with_zero_aftertax_basis_makes_conversion_fully_taxable
# =============================================================================


def test_pro_rata_with_zero_aftertax_basis_fully_taxable(api):
    """PRD §3.5: "Otherwise the nontaxable portion is gross multiplied by
    aftertax, floor-divided by the sum of pretax and aftertax; the taxable
    portion is gross minus the nontaxable portion."

    With pretax=200000, aftertax=0: nontax = 200000*0//200000 = 0;
    taxable = 200000.

    Design: Corner/calculations/pro_rata_with_zero_aftertax_basis_makes_conversion_fully_taxable
    """
    set_clock("2026-06-01T00:00:00Z")
    will = create_owner(
        full_name="Will",
        date_of_birth="1981-03-03",
        tax_id_last4="2323",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    trad = create_account(will["id"], "TRADITIONAL")
    roth = create_account(will["id"], "ROTH")

    fund_account_with_contribution(
        account_id=trad["id"],
        owner_id=will["id"],
        tax_year=2026,
        amount_cents=200_000,
        contribution_kind="PRETAX",
    )

    conv = initiate_conversion(
        source_account_id=trad["id"],
        target_account_id=roth["id"],
        owner_id=will["id"],
        gross_amount_cents=200_000,
    )
    refreshed = get_account(trad["id"], make_account_owner_headers(will["id"]))
    completed = complete_conversion(conv["id"], will["id"], refreshed["version"])

    assert completed["taxable_amount_cents"] == 200_000
    assert completed["nontaxable_amount_cents"] == 0
    assert completed["status"] == "COMPLETED"

    # Target Roth received the gross amount.
    roth_after = get_account(roth["id"], make_account_owner_headers(will["id"]))
    assert roth_after["cash_balance_cents"] == 200_000


# =============================================================================
# Corner: invalid conversion pair (owner mismatch)
# =============================================================================


def test_invalid_conversion_pair_owner_mismatch_rejected(api):
    """PRD §3.5: "The source and target must form a valid pair: the source
    must be `TRADITIONAL` and the target must be `ROTH`, and both accounts
    must share the same `owner_id`; any violation yields
    `ERR_INVALID_CONVERSION_PAIR`."

    Design: Corner/validations/invalid_conversion_pair_owner_mismatch_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    yara = create_owner(
        full_name="Yara",
        date_of_birth="1981-05-05",
        tax_id_last4="2525",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    zach = create_owner(
        full_name="Zach",
        date_of_birth="1981-06-06",
        tax_id_last4="2626",
        filing_status="SINGLE",
        modified_agi_cents=12_000_000,
    )
    yara_trad = create_account(yara["id"], "TRADITIONAL")
    zach_roth = create_account(zach["id"], "ROTH")

    fund_account_with_contribution(
        account_id=yara_trad["id"],
        owner_id=yara["id"],
        tax_year=2026,
        amount_cents=100_000,
        contribution_kind="AFTERTAX",
    )

    res = api.create_conversion(
        {
            "source_account_id": yara_trad["id"],
            "target_account_id": zach_roth["id"],
            "gross_amount_cents": 100_000,
        },
        make_account_owner_headers(yara["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_CONVERSION_PAIR.value)
