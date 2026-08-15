"""Depreciation run epoch rules and the append-only ledger line contract."""
from test_helpers import (
    ACCT,
    ApiErrorId,
    assert_depreciation_entry,
    book_entries,
    create_and_post_run,
    create_class,
    create_in_service_asset,
    validate_error,
    validate_success,
)


def test_run_period_gap_and_duplicate_open_slot_rejected(api):
    """PRD §2.7: "The first depreciation run ever created may target any period.
    Thereafter, a newly created run's `period` must be exactly one calendar month
    after the latest `POSTED` run's period; any other gap or overlap is rejected
    with `ERR_PERIOD_GAP` (HTTP 409)."
    PRD §2.7: "creating a second run for a period that already has an `OPEN` run
    is rejected with `ERR_DUPLICATE_RUN_PERIOD` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/depreciation_run_period_slot_rules
    """
    create_and_post_run("2026-01")

    gap = api.create_depreciation_run({"period": "2026-03"}, ACCT)
    validate_error(gap, ApiErrorId.ERR_PERIOD_GAP, 409)

    created = validate_success(
        api.create_depreciation_run({"period": "2026-02"}, ACCT), 201
    )
    assert created["status"] == "OPEN"

    dup = api.create_depreciation_run({"period": "2026-02"}, ACCT)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_RUN_PERIOD, 409)


def test_posted_period_slot_sealed(api):
    """PRD §2.7: "At most one run in status `OPEN` or `POSTED` may exist for a
    given period: creating a second run for a period that already has an `OPEN`
    run is rejected with `ERR_DUPLICATE_RUN_PERIOD` (HTTP 409), and for a period
    that already has a `POSTED` run with `ERR_PERIOD_ALREADY_POSTED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/depreciation_run_period_slot_rules
    """
    create_and_post_run("2026-01")
    run = validate_success(
        api.create_depreciation_run({"period": "2026-02"}, ACCT), 201
    )
    validate_success(api.post_depreciation_run(run["id"], ACCT), 200)

    sealed = api.create_depreciation_run({"period": "2026-02"}, ACCT)
    validate_error(sealed, ApiErrorId.ERR_PERIOD_ALREADY_POSTED, 409)


def test_below_basis_keeps_asset_in_service(api):
    """PRD §3.3: "After an asset's entries are applied, if its
    `accumulated_book_cents` has reached the depreciable basis — acquisition cost
    minus salvage minus impairment — the asset automatically transitions from
    `IN_SERVICE` to `FULLY_DEPRECIATED`; the tax ledger never triggers this
    transition."

    Design: Difficulty/boundary_precision_check/full_depreciation_exact_equality_transition
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-900", description="Tool set",
        acquisition_cost_cents=24000, useful_life_months=2,
    )
    create_and_post_run("2026-01")

    after = validate_success(api.get_fixed_asset(asset["id"], ACCT), 200)
    assert after["accumulated_book_cents"] == 12000
    assert after["accumulated_book_cents"] < 24000
    assert after["status"] == "IN_SERVICE", (
        "strictly below the depreciable basis: no transition"
    )


def test_exact_basis_equality_transitions_and_ends_eligibility(api):
    """PRD §3.3: "After an asset's entries are applied, if its
    `accumulated_book_cents` has reached the depreciable basis — acquisition cost
    minus salvage minus impairment — the asset automatically transitions from
    `IN_SERVICE` to `FULLY_DEPRECIATED`; the tax ledger never triggers this
    transition."
    PRD §3.3: "the asset must be `IN_SERVICE` (assets in `DRAFT`,
    `FULLY_DEPRECIATED`, or `DISPOSED` are excluded)"

    Design: Difficulty/boundary_precision_check/full_depreciation_exact_equality_transition
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-900", description="Tool set",
        acquisition_cost_cents=24000, useful_life_months=2,
    )
    create_and_post_run("2026-01")
    create_and_post_run("2026-02")

    after = validate_success(api.get_fixed_asset(asset["id"], ACCT), 200)
    assert after["accumulated_book_cents"] == 24000, (
        "exact equality with the depreciable basis triggers the transition"
    )
    assert after["status"] == "FULLY_DEPRECIATED"

    third = create_and_post_run("2026-03")
    assert third["entries_created_count"] == 0, (
        "a FULLY_DEPRECIATED asset is ineligible in later runs"
    )
    final = validate_success(api.get_fixed_asset(asset["id"], ACCT), 200)
    assert final["accumulated_book_cents"] == 24000


def test_depreciation_entry_immutable_ledger_line(api):
    """PRD §2.4: "The exception is the `DepreciationEntry` ledger line.
    Depreciation entries are immutable once created: they carry only `id` and
    `created_at` and have **no** `updated_at` and **no** `version` field. No
    endpoint modifies or deletes a depreciation entry."
    PRD §3.3: "Every entry created is a `DepreciationEntry` with `source` equal
    to `RUN`, the run's id recorded as its `run_id`, the `asset_id`, the
    `ledger`, the `period`, and the `amount_cents`; its `disposal_id` is null."

    Design: Corner/entities/depreciation_entry_immutable_ledger_line
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-004", description="Entry source",
        acquisition_cost_cents=24000, useful_life_months=2,
    )
    run = create_and_post_run("2026-01")

    entries = book_entries(asset["id"])
    assert len(entries) == 1
    entry_id = entries[0]["id"]

    entry = validate_success(api.get_depreciation_entry(entry_id, ACCT), 200)
    assert_depreciation_entry(entry)
    assert entry["ledger"] == "BOOK"
    assert entry["period"] == "2026-01"
    assert entry["amount_cents"] == 12000
    assert entry["source"] == "RUN"
    assert entry["run_id"] == run["id"]
    assert entry["disposal_id"] is None
