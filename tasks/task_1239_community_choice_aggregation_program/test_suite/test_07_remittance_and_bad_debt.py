"""Remittance waterfall, settlement cascades, OCC on the extract version,
terminal lockdown, segregation of duties, and the bad-debt true-up split."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_bad_debt_pool,
    assert_remittance_file,
    create_account_spec,
    create_pool,
    create_remittance,
    get_account,
    get_authority,
    get_extract,
    get_pool,
    make_billing_coordinator_headers,
    make_finance_controller_headers,
    reconcile_remittance,
    set_clock,
    setup_accepted_extract,
    setup_active_authority,
    setup_enrolled_accounts,
    setup_pool_closed_after_writeoff,
    setup_settled_extract,
    settle_remittance,
    validate_error,
    validate_success,
)

BC = TEST_USERS["billing_coordinator_headers"]
FC = TEST_USERS["finance_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
UL = TEST_USERS["utility_liaison_headers"]


def test_remittance_settle_cascades_extract_to_settled(api):
    """PRD §3.7: "Its cascade has two hops: the matching billing extract transitions `ACCEPTED → SETTLED`, and that extract settlement attributes its `total_billed_cents` to the bad-debt pool whose `pool_period` contains the billing month, incrementing the pool's `billed_generation_cents`. Both file and extract end in `SETTLED`, terminal."

    Design: Difficulty/transitive_cascade/remittance_settle_cascade_extract_pool
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-5001")]
    )
    account_id = enrolled["account_ids"][0]
    extract = setup_accepted_extract("2026-05", [(account_id, 1000)])
    assert extract["total_billed_cents"] == 11400

    remittance = create_remittance("2026-05", 11400, utility_fee_bps=0)
    reconcile_remittance(remittance["id"], extract["version"])
    pool = create_pool("2026-Q2")

    settled = settle_remittance(remittance["id"])
    assert_remittance_file(settled)
    assert settled["status"] == "SETTLED"

    extract_after = get_extract(extract["id"])
    assert extract_after["status"] == "SETTLED", (
        "hop 1: the matching extract is carried to SETTLED by the settle"
    )


def test_remittance_settle_attributes_billed_cents_to_pool(api):
    """PRD §3.7: "Its cascade has two hops: the matching billing extract transitions `ACCEPTED → SETTLED`, and that extract settlement attributes its `total_billed_cents` to the bad-debt pool whose `pool_period` contains the billing month, incrementing the pool's `billed_generation_cents`. Both file and extract end in `SETTLED`, terminal."
    PRD §3.7: "The file's `applied_cents` is set to the full `net_remittance_cents`, and reconciliation increments the matching extract's `version` by 1."

    Design: Difficulty/transitive_cascade/remittance_settle_cascade_extract_pool
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-5001")]
    )
    account_id = enrolled["account_ids"][0]
    extract = setup_accepted_extract("2026-05", [(account_id, 1000)])
    remittance = create_remittance("2026-05", 11400, utility_fee_bps=0)
    reconcile_remittance(remittance["id"], extract["version"])
    pool = create_pool("2026-Q2")
    assert get_pool(pool["id"])["billed_generation_cents"] == 0

    settle_remittance(remittance["id"])

    pool_after = get_pool(pool["id"])
    assert pool_after["billed_generation_cents"] == 11400, (
        "hop 2: the extract's SETTLED transition attributes its billed total "
        "to the pool whose period contains the billing month"
    )

    account = get_account(account_id)
    assert account["cumulative_remitted_cents"] == 11400
    assert account["cumulative_billed_cents"] == 11400, "open balance is zero"


def test_reconcile_applies_waterfall_to_accounts(api):
    """PRD §3.7: "It then applies the net cash as a waterfall: eligible accounts are those with billing lines in the matching month's extract and a positive open balance (billed minus remitted), among both `ENROLLED` and `OPTED_BACK_TO_BUNDLED` accounts; they are filled in order of account `created_at` ascending — a tie is impossible at one-millisecond resolution, but if one ever occurred the fallback is `updated_at` ascending, never `id` — each credit incrementing the account's `cumulative_remitted_cents`."
    PRD §3.7: "The file's `applied_cents` is set to the full `net_remittance_cents`, and reconciliation increments the matching extract's `version` by 1."

    Design: Difficulty/compensating_invariant/remittance_reconcile_dispute_conserves_remitted_cents
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[
            create_account_spec(utility_account_number="U-9001"),
            create_account_spec(utility_account_number="U-9002"),
        ]
    )
    a1, a2 = enrolled["account_ids"]
    extract = setup_accepted_extract("2026-05", [(a1, 1000), (a2, 1000)])

    remittance = create_remittance("2026-05", 22800, utility_fee_bps=0)
    assert remittance["net_remittance_cents"] == 22800
    reconciled = reconcile_remittance(remittance["id"], extract["version"])
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["applied_cents"] == 22800, (
        "applied_cents equals the full net remittance"
    )

    for account_id in (a1, a2):
        account = get_account(account_id)
        assert account["cumulative_remitted_cents"] == 11400
        assert account["cumulative_billed_cents"] == 11400


def test_dispute_reverses_reconcile_credits_exactly(api):
    """PRD §3.7: "A `UtilityLiaison` may dispute the file, moving it `RECONCILED → DISPUTED`, and the dispute compensates: every remittance credit applied at reconciliation is reversed from the affected accounts, and `applied_cents` returns to 0."

    Design: Difficulty/compensating_invariant/remittance_reconcile_dispute_conserves_remitted_cents
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[
            create_account_spec(utility_account_number="U-9001"),
            create_account_spec(utility_account_number="U-9002"),
        ]
    )
    a1, a2 = enrolled["account_ids"]
    extract = setup_accepted_extract("2026-05", [(a1, 1000), (a2, 1000)])
    remittance = create_remittance("2026-05", 22800, utility_fee_bps=0)
    reconcile_remittance(remittance["id"], extract["version"])

    disputed = validate_success(
        api.dispute_remittance_file(remittance["id"], {}, UL), 200
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["applied_cents"] == 0

    # The compensating action restores the pre-reconcile invariant exactly:
    # remitted credits reversed, billed ledger untouched.
    for account_id in (a1, a2):
        account = get_account(account_id)
        assert account["cumulative_remitted_cents"] == 0
        assert account["cumulative_billed_cents"] == 11400


def test_occ_remittance_reconcile_stale_extract_version(api):
    """PRD §2.8: "Second, reconciling a remittance file requires the request to carry `expected_extract_version`, holding the current `version` of the matching billing extract. The waterfall application distributes cash against the extract's line set, and a newer extract version means that line set changed since the reconciler last observed it; a mismatch is rejected with `ERR_STALE_EXTRACT_VERSION` (HTTP 412)."
    PRD §3.7: "The file's `applied_cents` is set to the full `net_remittance_cents`, and reconciliation increments the matching extract's `version` by 1."

    Design: Corner/complexity_layers/occ_remittance_reconcile_stale_extract_version
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-O01")]
    )
    account_id = enrolled["account_ids"][0]
    extract = setup_accepted_extract("2026-05", [(account_id, 1000)])
    observed_version = extract["version"]

    rem1 = create_remittance("2026-05", 5000, utility_fee_bps=0)
    reconcile_remittance(rem1["id"], observed_version)
    assert get_extract(extract["id"])["version"] == observed_version + 1, (
        "the first reconcile advanced the extract version"
    )

    rem2 = create_remittance("2026-05", 6400, utility_fee_bps=0)
    stale = api.reconcile_remittance_file(
        rem2["id"],
        {"expected_extract_version": observed_version},
        make_billing_coordinator_headers("bc-1"),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_EXTRACT_VERSION)

    rem2_after = validate_success(api.get_remittance_file(rem2["id"], BC), 200)
    assert rem2_after["status"] == "RECEIVED"
    assert get_account(account_id)["cumulative_remitted_cents"] == 5000, (
        "the rejected second reconcile applied nothing further"
    )


def test_terminal_state_lockdown_settled_extract(api):
    """PRD §2.9: "6. **Terminal lockdown** — triggers fired against a terminal-state resource (a `SETTLED` extract or remittance, a `TRUED_UP` pool, an `ACCEPTED_BY_CPUC` filing) yield `ERR_ALREADY_TERMINAL`, an audit-distinct code kept separate from `ERR_INVALID_STATE` so closed books are visibly closed."

    Design: Corner/state_machines/terminal_state_lockdown_settled_extract
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-3001")]
    )
    account_id = enrolled["account_ids"][0]
    extract, _remittance = setup_settled_extract("2026-05", [(account_id, 1000)])
    assert extract["status"] == "SETTLED"
    assert get_account(account_id)["cumulative_billed_cents"] == 11400

    res = api.utility_accept_extract(extract["id"], {}, UL)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)

    assert get_account(account_id)["cumulative_billed_cents"] == 11400, (
        "no double credit is posted against a settled extract"
    )


def test_segregation_of_duties_remittance_settle(api):
    """PRD §3.7: "Settlement is the fiscal close of the loop and belongs to a `FinanceController` — with segregation of duties against whoever reconciled the file: the acting id must differ from the reconciler's id recorded on the file, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_remittance_settle
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-S01")]
    )
    extract = setup_accepted_extract(
        "2026-05", [(enrolled["account_ids"][0], 1000)]
    )
    remittance = create_remittance("2026-05", 11400, utility_fee_bps=0)
    reconcile_remittance(remittance["id"], extract["version"], reconciler_id="bc-01")

    # The settler carries the same opaque operator id as the reconciler.
    res = api.settle_remittance_file(
        remittance["id"], {}, make_finance_controller_headers("bc-01")
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    after = validate_success(api.get_remittance_file(remittance["id"], FC), 200)
    assert after["status"] == "RECONCILED"


def test_account_close_fiscal_gate_zero_balance(api):
    """PRD §3.3: "Closing an account — from either `ENROLLED` or `OPTED_BACK_TO_BUNDLED` — is a fiscal act: it requires the open balance, `cumulative_billed_cents` minus `cumulative_remitted_cents`, to be exactly zero. A nonzero balance is rejected with `ERR_FISCAL_GATE`."

    Design: Corner/validations/account_close_fiscal_gate_zero_balance
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-7001")]
    )
    account_id = enrolled["account_ids"][0]
    setup_accepted_extract("2026-05", [(account_id, 1000)])
    assert get_account(account_id)["cumulative_billed_cents"] == 11400

    res = api.close_service_account(account_id, {}, CS)
    validate_error(res, ApiErrorId.ERR_FISCAL_GATE)

    assert get_account(account_id)["enrollment_state"] == "ENROLLED"


def _setup_pool_closed_after_writeoff(api):
    """Build the closed-pool scenario via the shared fixture and assert the
    seeded reserve before returning it."""
    closed = setup_pool_closed_after_writeoff()
    assert get_authority()["climate_reserve_balance_cents"] == 250000
    return closed


def test_bad_debt_trueup_share_split(api):
    """PRD §3.8: "The sharing split is then computed: the CCA's share, `cca_share_cents`, is the smaller of the written-off total and the cap, where the cap is `billed_generation_cents` times the authority's `bad_debt_trueup_cap_pct` rounded half up to whole cents. The boundary is inclusive of the cap — when the written-off total equals the cap exactly, the CCA absorbs all of it. The utility's share, `utility_share_cents`, is whatever remains of the written-off total after the CCA share."
    PRD §3.8: "The pool's `billed_generation_cents` is the total billed generation revenue across every `SETTLED` extract whose billing month falls inside the pool period — the denominator for the statutory cap."

    Design: Difficulty/transitive_cascade/bad_debt_trueup_reserve_drain_cascade
    """
    closed = _setup_pool_closed_after_writeoff(api)
    assert_bad_debt_pool(closed)
    # Only the SETTLED April extract (11400 c) feeds the denominator; the
    # May extract was accepted but never settled.
    assert closed["billed_generation_cents"] == 11400
    assert closed["written_off_cents"] == 28500000
    # cap = round_half_up(11400 * 0.01) = 114; share = min(28500000, 114)
    assert closed["cca_share_cents"] == 114
    assert closed["utility_share_cents"] == 28500000 - 114

    trued = validate_success(
        api.true_up_bad_debt_pool(
            closed["id"], {}, make_finance_controller_headers("controller-f2")
        ),
        200,
    )
    assert trued["status"] == "TRUED_UP"
    assert trued["reserve_draw_cents"] == 114, "reserve covers the whole share"
    assert trued["expensed_cents"] == 0


def test_bad_debt_trueup_reserve_draw_cascade(api):
    """PRD §3.8: "The cascade has three hops: the Authority's `climate_reserve_balance_cents` is debited by `reserve_draw_cents`, which equals the CCA share clamped to the reserve balance per §2.7; that debit increments the Authority's `version` by 1 and refreshes its `updated_at`; and `expensed_cents` is recorded as the CCA share minus the reserve draw — the portion of the share the reserve could not cover."

    Design: Difficulty/transitive_cascade/bad_debt_trueup_reserve_drain_cascade
    """
    closed = _setup_pool_closed_after_writeoff(api)
    before = get_authority()
    assert before["climate_reserve_balance_cents"] == 250000

    trued = validate_success(
        api.true_up_bad_debt_pool(
            closed["id"], {}, make_finance_controller_headers("controller-f2")
        ),
        200,
    )
    assert trued["status"] == "TRUED_UP"

    after = get_authority()
    # hop 1: 250000 - reserve_draw_cents(114) = 249886
    assert after["climate_reserve_balance_cents"] == 249886
    # hop 2: the reserve debit is an Authority mutation
    assert after["version"] == before["version"] + 1
