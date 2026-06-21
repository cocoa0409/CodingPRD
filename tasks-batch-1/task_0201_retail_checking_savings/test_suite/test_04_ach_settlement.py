"""ACH origination settlement, posting order, reversal, and optimistic concurrency
(PRD §2.6, §3.12–§3.14).

Covers queue-A difficulty instances for the posting-order fee divergence, the
frozen-debtor return, and the two-account conservation invariant, plus queue-B corner
instances for OCC stale-version, leg version increments, settlement cascades, and
account-not-found.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_account_holder_headers,
    make_officer_headers,
    set_clock,
    create_apy_tier,
    open_account,
    open_account_with_courtesy_pay,
    open_account_with_deposit,
    stage_batch_with_legs,
    settle_batch,
    list_all_fee_assessments,
)
from test_helpers.factories import (
    ach_origination_payload,
    settle_payload,
    reverse_payload,
)


# ===========================================================================
# Queue A — dual_variant_calc / ach_posting_order_diverges_fee_total
# ===========================================================================
def test_chronological_posting_one_overdraft_fee(api):
    """PRD §3.13: "Under `CHRONOLOGICAL` posting — the canonical, consumer-friendly
    default — legs post oldest-first, ordered ascending by each leg's `created_at`."
    PRD §3.13: "evaluated against the debtor account's current `available_balance_cents`
    as it stands after every prior leg in this same settlement has already been
    applied — the running balance carries leg to leg."

    Debtor ledger 5000, courtesy limit 6000; legs 4000 then 7000 chronological. 4000
    posts (avail 1000), 7000 posts into overdraft (avail -6000 == floor) with one
    OVERDRAFT fee 3000: debtor ledger 5000 - 4000 - 7000 - 3000 = -9000.

    Design: Difficulty/dual_variant_calc/ach_posting_order_diverges_fee_total
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_courtesy_pay(deposit_cents=5000, limit_cents=6000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "3333"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("DEBIT", 4000), ("DEBIT", 7000)],
        posting_order="CHRONOLOGICAL",
    )
    settle_batch(o_id, version)

    acct_after = validate_success(api.get_account(acct_d["id"], make_officer_headers()), 200)
    assert acct_after["ledger_balance_cents"] == -9000

    fees = list_all_fee_assessments(acct_d["id"], cust_d["id"])
    assert sum(f["fee_amount_cents"] for f in fees) == 3000, "one OVERDRAFT fee"


def test_high_to_low_posting_overdraft_plus_nsf_fee(api):
    """PRD §3.13: "Under `HIGH_TO_LOW` posting, all `CREDIT` legs settle first, and then
    the `DEBIT` legs settle ordered by `amount_cents` descending, with ties broken by
    ascending `created_at`."
    PRD §3.13: "high-to-low draining the balance with the largest debit first bounces
    more of the small debits, so its total fees are always at least those of
    chronological posting for the same legs."

    Same legs 4000/7000, debtor ledger 5000, courtesy limit 6000, HIGH_TO_LOW. 7000
    posts first into overdraft (avail -2000, OVERDRAFT fee 3000 -> ledger -5000), then
    4000 would breach floor -6000 so it is RETURNED NSF (NSF fee 3500): ledger
    5000 - 7000 - 3000 - 3500 = -8500, fees 6500.

    Design: Difficulty/dual_variant_calc/ach_posting_order_diverges_fee_total
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_courtesy_pay(deposit_cents=5000, limit_cents=6000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "3333"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("DEBIT", 4000), ("DEBIT", 7000)],
        posting_order="HIGH_TO_LOW",
    )
    settle_batch(o_id, version)

    acct_after = validate_success(api.get_account(acct_d["id"], make_officer_headers()), 200)
    assert acct_after["ledger_balance_cents"] == -8500

    fees = list_all_fee_assessments(acct_d["id"], cust_d["id"])
    assert sum(f["fee_amount_cents"] for f in fees) == 6500, "one OVERDRAFT 3000 + one NSF 3500"


# ===========================================================================
# Queue A — cross_entity_state_dependency / ach_debit_returns_when_debtor_frozen
# ===========================================================================
def test_ach_debit_returns_when_debtor_frozen(api):
    """PRD §3.8: "While an account is `FROZEN`, debit settlement legs against it are
    returned with `return_reason_code` of `ACCOUNT_FROZEN` rather than posting."
    PRD §3.13: "one that would breach the courtesy-pay floor, or that meets a frozen
    account, is returned".

    A settling DEBIT leg against a FROZEN debtor is RETURNED ACCOUNT_FROZEN; the debtor
    ledger is unchanged and no NSF fee is assessed.

    Design: Difficulty/cross_entity_state_dependency/ach_debit_returns_when_debtor_frozen
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=30000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "8181"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("DEBIT", 5000)], posting_order="CHRONOLOGICAL"
    )
    validate_success(
        api.freeze_account(acct_d["id"], make_officer_headers("officer-1")), 200
    )
    settle_batch(o_id, version)

    txns = validate_success(
        api.list_transactions(make_officer_headers(), params={"ach_origination_id": o_id, "limit": 100}),
        200,
    )
    debit_txns = [t for t in txns if t["direction"] == "DEBIT"]
    assert len(debit_txns) == 1
    assert debit_txns[0]["status"] == "RETURNED"
    assert debit_txns[0]["return_reason_code"] == "ACCOUNT_FROZEN"

    acct_after = validate_success(api.get_account(acct_d["id"], make_officer_headers()), 200)
    assert acct_after["ledger_balance_cents"] == 30000

    fees = list_all_fee_assessments(acct_d["id"], cust_d["id"])
    assert len(fees) == 0, "a frozen return is not an NSF fee"


def test_frozen_debtor_leg_outcome_returned_nsf(api):
    """PRD §3.13: "A debit leg that clears posts; one that would breach the courtesy-pay
    floor, or that meets a frozen account, is returned, taking `settlement_outcome` of
    `RETURNED_NSF`".

    The produced leg's settlement_outcome is RETURNED_NSF when the debtor is frozen.

    Design: Difficulty/cross_entity_state_dependency/ach_debit_returns_when_debtor_frozen
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=30000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "8282"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("DEBIT", 5000)], posting_order="CHRONOLOGICAL"
    )
    validate_success(api.freeze_account(acct_d["id"], make_officer_headers("officer-1")), 200)
    settle_batch(o_id, version)

    legs = validate_success(
        api.list_ach_legs_of_origination(o_id, make_officer_headers(), params={"limit": 100}), 200
    )
    debit_legs = [l for l in legs if l["leg_role"] == "DEBIT"]
    assert len(debit_legs) == 1
    assert debit_legs[0]["settlement_outcome"] == "RETURNED_NSF"


# ===========================================================================
# Queue A — compensating_invariant / ach_settle_reverse_conserves_two_account_total
# ===========================================================================
def test_settle_then_reverse_conserves_two_account_total(api):
    """PRD §3.14: "The conserved quantity is the two-account ledger total: summed across
    the debtor and creditor accounts, `ledger_balance_cents` after the reversal equals
    what it was across those two accounts before the batch was ever settled."
    PRD §3.14: "a settle followed by a reverse leaves the combined ledger of the two
    accounts exactly where it started."

    Debtor 20000, creditor 0; batch CREDIT 5000 then DEBIT 8000. After settle debtor
    12000 / creditor 5000 (sum 17000). After reverse debtor 20000 / creditor 0 (sum
    20000 = pre-batch total).

    Design: Difficulty/compensating_invariant/ach_settle_reverse_conserves_two_account_total
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=20000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "1616"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("CREDIT", 5000), ("DEBIT", 8000)],
        posting_order="CHRONOLOGICAL",
    )
    settled = settle_batch(o_id, version)
    post_settle_version = settled["version"]

    d_after = validate_success(api.get_account(acct_d["id"], make_officer_headers()), 200)
    c_after = validate_success(api.get_account(acct_c["id"], make_officer_headers()), 200)
    assert d_after["ledger_balance_cents"] == 12000
    assert c_after["ledger_balance_cents"] == 5000

    reversed_o = validate_success(
        api.reverse_ach_origination(
            o_id, reverse_payload(post_settle_version), make_officer_headers("officer-1")
        ),
        200,
    )
    assert reversed_o["status"] == "REVERSED"

    d_final = validate_success(api.get_account(acct_d["id"], make_officer_headers()), 200)
    c_final = validate_success(api.get_account(acct_c["id"], make_officer_headers()), 200)
    assert d_final["ledger_balance_cents"] == 20000
    assert c_final["ledger_balance_cents"] == 0
    assert d_final["ledger_balance_cents"] + c_final["ledger_balance_cents"] == 20000


def test_reverse_restores_each_account_ledger(api):
    """PRD §3.14: "For every `POSTED` transaction the batch produced — reachable through
    its legs' `produced_transaction_id` — the system posts an equal-and-opposite
    `POSTED` transaction of the same `amount_cents` (a credit reverses a debit and vice
    versa)."

    Design: Difficulty/compensating_invariant/ach_settle_reverse_conserves_two_account_total
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=20000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "1617"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("CREDIT", 5000), ("DEBIT", 8000)],
        posting_order="CHRONOLOGICAL",
    )
    settled = settle_batch(o_id, version)
    validate_success(
        api.reverse_ach_origination(
            o_id, reverse_payload(settled["version"]), make_officer_headers("officer-1")
        ),
        200,
    )
    d_final = validate_success(api.get_account(acct_d["id"], make_officer_headers()), 200)
    c_final = validate_success(api.get_account(acct_c["id"], make_officer_headers()), 200)
    assert d_final["ledger_balance_cents"] == 20000
    assert c_final["ledger_balance_cents"] == 0


# ===========================================================================
# Queue B — cross_cutting / occ_settle_stale_version_conflict
# ===========================================================================
def test_settle_stale_version_rejected(api):
    """PRD §2.6: "If another writer has advanced the version since the client last read
    it — for example by adding or removing a leg, which legitimately bumps the version —
    the settle is rejected with `ERR_STALE_VERSION` (HTTP 412), because the settler's
    view of which legs will post is stale."

    Settling with version-1 (a stale value one behind the post-leg version) is rejected
    and the batch stays STAGED.

    Design: Corner/cross_cutting_complexity_layers/occ_settle_stale_version_conflict
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=50000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "4040"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("DEBIT", 1000)], posting_order="CHRONOLOGICAL"
    )
    res = api.settle_ach_origination(
        o_id, settle_payload(version - 1), make_officer_headers("officer-1")
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    o_after = validate_success(api.get_ach_origination(o_id, make_officer_headers()), 200)
    assert o_after["status"] == "STAGED"


# ===========================================================================
# Queue B — cross_cutting / occ_version_increments_on_leg_add
# ===========================================================================
def test_leg_add_increments_version_by_one(api):
    """PRD §2.6: "a matching value lets the leg be created and advances the origination's
    `version` by one."
    PRD §3.13: "Settlement is defined only from `STAGED` (otherwise `ERR_INVALID_STATE`),
    requires `expected_ach_origination_version` to match the origination's current
    `version` (otherwise `ERR_STALE_VERSION`, HTTP 412, per Section 2.6), and requires
    both the debtor and creditor accounts to exist and be not `CLOSED` (otherwise
    `ERR_ACCOUNT_NOT_FOUND`)."

    Adding a leg bumps version by exactly 1; a settle with the post-leg version succeeds.

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_leg_add
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=50000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "4242"})

    staged = validate_success(
        api.create_ach_origination(
            ach_origination_payload(acct_d["id"], acct_c["id"], "CHRONOLOGICAL"),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    pre_version = staged["version"]
    from test_helpers.factories import ach_leg_payload
    validate_success(
        api.add_ach_leg(
            staged["id"], ach_leg_payload("DEBIT", 1000, pre_version),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    # PRD §2.6/§3.12: the leg add advances the ORIGINATION's version by one. The bumped
    # value lives on the AchOrigination resource (the freshly created AchLeg carries its
    # own version, which begins at its initial value per PRD §2.4), so read it back from
    # the origination.
    o_after = validate_success(api.get_ach_origination(staged["id"], make_officer_headers()), 200)
    new_version = o_after["version"]
    assert new_version == pre_version + 1

    settled = validate_success(
        api.settle_ach_origination(
            staged["id"], settle_payload(new_version), make_officer_headers("officer-1")
        ),
        200,
    )
    assert settled["status"] == "SETTLED"


# ===========================================================================
# Queue B — cross_cutting / reverse_stale_origination_conflict
# ===========================================================================
def test_reverse_stale_version_rejected(api):
    """PRD §2.6: "When a settled batch is reversed, the reverse request must likewise
    carry `expected_ach_origination_version` equal to the origination's current
    `version`; a mismatch (for instance, because the act of settling already advanced
    the version past what the reverser last observed) is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Reversing with the pre-settle version (one behind the post-settle version) is
    rejected and the batch stays SETTLED.

    Design: Corner/cross_cutting_complexity_layers/reverse_stale_origination_conflict
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=50000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "4444"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("DEBIT", 1000)], posting_order="CHRONOLOGICAL"
    )
    settled = settle_batch(o_id, version)
    # Reverse with version-1 (the pre-settle version, now stale).
    res = api.reverse_ach_origination(
        o_id, reverse_payload(settled["version"] - 1), make_officer_headers("officer-1")
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    o_after = validate_success(api.get_ach_origination(o_id, make_officer_headers()), 200)
    assert o_after["status"] == "SETTLED"


# ===========================================================================
# Queue B — cross_cutting / ach_settle_cascade_credits_direct_deposit
# ===========================================================================
def test_ach_settle_credits_creditor_and_bumps_last_activity(api):
    """PRD §3.13: "Each `CREDIT` leg posts its `amount_cents` as a credit to the creditor
    account and always posts unless that creditor account is closed."
    PRD §3.13: "credit legs to the creditor account refresh that account's
    `last_activity_date` — so a direct deposit reactivates a dormant creditor."

    Design: Corner/cross_cutting_complexity_layers/ach_settle_cascade_credits_direct_deposit
    """
    set_clock("2026-05-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_d, acct_d = open_account_with_deposit(deposit_cents=20000)
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "4747"})

    o_id, version = stage_batch_with_legs(
        acct_d["id"], acct_c["id"], legs=[("CREDIT", 6000)], posting_order="CHRONOLOGICAL"
    )
    settled = settle_batch(o_id, version)

    c_after = validate_success(api.get_account(acct_c["id"], make_officer_headers()), 200)
    assert c_after["ledger_balance_cents"] == 6000
    assert c_after["last_activity_date"] == "2026-05-01"

    o_after = validate_success(api.get_ach_origination(o_id, make_officer_headers()), 200)
    assert o_after["total_credit_cents"] == 6000


# ===========================================================================
# Queue B — errors / account_not_found_on_ach_origination
# ===========================================================================
def test_account_not_found_on_ach_origination(api):
    """PRD §2.8: "`ERR_ACCOUNT_NOT_FOUND` when a referenced debtor, creditor, or target
    account does not resolve".

    Design: Corner/errors/account_not_found_on_ach_origination
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust_c, acct_c = open_account(customer_overrides={"tax_id_last4": "3535"})
    res = api.create_ach_origination(
        ach_origination_payload(
            "00000000-0000-0000-0000-000000000000", acct_c["id"], "CHRONOLOGICAL"
        ),
        make_officer_headers("officer-1"),
    )
    validate_error(res, "ERR_ACCOUNT_NOT_FOUND", expected_status=404)
