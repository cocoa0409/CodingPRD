"""Budget period lifecycle: zero-based close, OCC on household version, rollover carry,
recategorize period mismatch, duplicate month, account archive guards.

Translates Difficulty queue (A) resource_temporal_overlap (period),
cross_entity_state_dependency (account), boundary_precision_check (archive) and
Corner queue (B) state_machines/validations/cross_cutting (close, OCC, rollover, mismatch).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, admin_headers,
    ApiErrorId,
    create_household, create_account, ingest_transaction, post_transaction,
    ingest_and_post, setup_household_with_period, setup_household_period_category,
    open_period, create_category, observe_household_version, find_open_period,
    find_category_by_name,
)


def test_occ_correct_version_close_succeeds_and_bumps_version(api):
    """PRD §2.9: "The server compares that value against the household's current version;
    if another writer has advanced the household's version since the client read it, the
    close is rejected with ERR_STALE_HOUSEHOLD at HTTP 412."
    PRD §3.5: "the household's current_period_id is repointed to it; and the household's
    version increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_close_succeeds
    """
    hh, owner_headers, period = setup_household_with_period(
        month="2026-01", income_expected_cents=0)
    hv = observe_household_version(hh["id"], owner_headers)
    resp = api.close_budget_period(
        hh["id"], period["id"], {"expected_household_version": hv}, owner_headers)
    data = validate_success(resp)
    assert data["status"] == "CLOSED", f"period closed, got {data['status']}"
    after = validate_success(api.get_household(hh["id"], owner_headers))
    assert after["version"] == hv + 1, \
        f"version bumps by 1, expected {hv + 1}, got {after['version']}"


def test_occ_stale_household_version_on_close_rejected(api):
    """PRD §2.9: "The close request must carry expected_household_version, which is the
    version of the household the client last observed. The server compares that value
    against the household's current version; if another writer has advanced the household's
    version since the client read it, the close is rejected with ERR_STALE_HOUSEHOLD at
    HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_household_version_on_close
    """
    hh, owner_headers, period = setup_household_with_period(
        month="2026-01", income_expected_cents=0)
    hv = observe_household_version(hh["id"], owner_headers)
    resp = api.close_budget_period(
        hh["id"], period["id"], {"expected_household_version": hv - 1}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_HOUSEHOLD)


def test_period_close_not_zero_based_rejected(api):
    """PRD §3.5: "The zero-based check requires the period's total_allocated_cents to equal
    its income_expected_cents; if every planned dollar has not been assigned to an envelope,
    the close is rejected with ERR_BUDGET_NOT_ZERO_BASED."

    Design: Corner/validations/period_close_not_zero_based_rejected
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        month="2026-01", income_expected_cents=10000, cat_name="Food",
        allocated_cents=3000)
    hv = observe_household_version(hh["id"], owner_headers)
    resp = api.close_budget_period(
        hh["id"], period["id"], {"expected_household_version": hv}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_BUDGET_NOT_ZERO_BASED)


def test_period_close_rolls_leftover_envelope(api):
    """PRD §3.5: "Rollover then runs: for each category in the closing period whose
    rollover_enabled is true and whose available_cents is greater than zero, a same-named
    category is created in the new period with its rollover_in_cents set to that leftover
    available_cents — the positive leftover is carried forward."

    Design: Corner/state_machines/period_close_rolls_leftover_envelope
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        month="2026-01", income_expected_cents=5000, cat_name="Food",
        allocated_cents=5000)
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    ingest_and_post(acc["id"], amount_cents=-2000, merchant_name="Mart",
                    budget_category_id=cat["id"])
    # Food now has available 3000 (5000 allocated - 2000 spent).
    hv = observe_household_version(hh["id"], owner_headers)
    closed = validate_success(api.close_budget_period(
        hh["id"], period["id"], {"expected_household_version": hv}, owner_headers))
    assert closed["status"] == "CLOSED"

    new_period = find_open_period(hh["id"], owner_headers)
    rolled = find_category_by_name(hh["id"], new_period["id"], owner_headers, "Food")
    assert rolled is not None, "rolled-forward Food category must exist in new period"
    assert rolled["rollover_in_cents"] == 3000, \
        f"leftover 3000 carried as rollover_in, got {rolled['rollover_in_cents']}"


def test_recategorize_wrong_period_category_rejected(api):
    """PRD §3.3: "The recategorize is permitted only when the household is not frozen
    (otherwise ERR_HOUSEHOLD_FROZEN) and when the target category exists and belongs to the
    household's current period (otherwise ERR_CATEGORY_PERIOD_MISMATCH)."

    Design: Corner/validations/recategorize_wrong_period_category_rejected
    """
    hh, owner_headers = create_household()
    p1 = open_period(hh["id"], owner_headers, month="2026-01", income_expected_cents=0)
    old_cat = create_category(hh["id"], p1["id"], owner_headers, name="Old",
                              allocated_cents=0)
    hv = observe_household_version(hh["id"], owner_headers)
    validate_success(api.close_budget_period(
        hh["id"], p1["id"], {"expected_household_version": hv}, owner_headers))
    # New current period now open; Old belongs to the CLOSED prior period.
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    txn = ingest_transaction(acc["id"], amount_cents=-1000, merchant_name="Store")
    post_transaction(acc["id"], txn["id"])
    resp = api.recategorize_transaction(
        acc["id"], txn["id"], {"budget_category_id": old_cat["id"]}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_PERIOD_MISMATCH)


def test_duplicate_period_month_rejected(api):
    """PRD §3.5: "A period's month is unique within the household, and only one period per
    household may be OPEN at a time; a duplicate month or a second open period is rejected
    with ERR_DUPLICATE_RESOURCE."

    Design: Difficulty/resource_temporal_overlap/duplicate_period_month_rejected
    """
    hh, owner_headers = create_household()
    open_period(hh["id"], owner_headers, month="2026-01", income_expected_cents=0)
    resp = api.create_budget_period(
        hh["id"], {"month": "2026-01", "income_expected_cents": 0}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_second_open_period_rejected(api):
    """PRD §3.5: "only one period per household may be OPEN at a time; a duplicate month or
    a second open period is rejected with ERR_DUPLICATE_RESOURCE."

    Design: Difficulty/resource_temporal_overlap/duplicate_period_month_rejected
    """
    hh, owner_headers = create_household()
    open_period(hh["id"], owner_headers, month="2026-01", income_expected_cents=0)
    # A different month, but a period is already OPEN -> still rejected.
    resp = api.create_budget_period(
        hh["id"], {"month": "2026-02", "income_expected_cents": 0}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_duplicate_category_name_in_period_rejected(api):
    """PRD §3.5: "A category is created with a name (unique within its period; a duplicate
    is ERR_DUPLICATE_RESOURCE)".

    Design: Corner/validations/duplicate_category_name_in_period_rejected
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        month="2026-01", income_expected_cents=5000, cat_name="Food",
        allocated_cents=5000)
    resp = api.create_category(
        hh["id"], period["id"], {"name": "Food", "allocated_cents": 0}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_archive_blocked_by_pending_transaction(api):
    """PRD §3.2: "Archival is permitted only when the account has no PENDING transactions;
    an attempt while pending transactions remain is rejected with
    ERR_PENDING_TRANSACTIONS_EXIST."

    Design: Difficulty/boundary_precision_check/archive_blocked_by_nonzero_pending_count
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    ingest_transaction(acc["id"], amount_cents=-1000, merchant_name="Store")
    resp = api.archive_account(hh["id"], acc["id"], owner_headers)
    validate_error(resp, ApiErrorId.ERR_PENDING_TRANSACTIONS_EXIST)


def test_archive_succeeds_with_zero_pending(api):
    """PRD §3.2: "An owner may archive an account, transitioning its status from LINKED to
    ARCHIVED. Archival is permitted only when the account has no PENDING transactions".

    Design: Difficulty/boundary_precision_check/archive_blocked_by_nonzero_pending_count
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    data = validate_success(api.archive_account(hh["id"], acc["id"], owner_headers))
    assert data["status"] == "ARCHIVED", \
        f"zero pending -> archive succeeds, got {data['status']}"


def test_transaction_create_blocked_by_account_archived(api):
    """PRD §3.3: "A transaction may be created only on a LINKED account; an attempt on an
    archived account is rejected with ERR_ACCOUNT_ARCHIVED."

    Design: Difficulty/cross_entity_state_dependency/transaction_create_blocked_by_account_archived
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    validate_success(api.archive_account(hh["id"], acc["id"], owner_headers))
    resp = api.create_transaction(
        acc["id"], {"amount_cents": -500, "merchant_name": "Late"}, admin_headers())
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ARCHIVED)


def test_inflow_ingest_blocked_by_account_archived(api):
    """PRD §3.3: "A transaction may be created only on a LINKED account; an attempt on an
    archived account is rejected with ERR_ACCOUNT_ARCHIVED."

    Design: Difficulty/cross_entity_state_dependency/transaction_create_blocked_by_account_archived
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    validate_success(api.archive_account(hh["id"], acc["id"], owner_headers))
    # A positive inflow ingest is equally gated on the LINKED status.
    resp = api.create_transaction(
        acc["id"], {"amount_cents": 2500, "merchant_name": "Refund"}, admin_headers())
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ARCHIVED)
