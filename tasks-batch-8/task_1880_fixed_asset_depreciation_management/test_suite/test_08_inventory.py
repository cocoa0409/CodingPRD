"""Physical inventory: count-line derivation, recount cycle, run gates, the
DAMAGED cascade, and location re-derivation."""
from test_helpers import (
    ACCT,
    CTRL,
    CLERK,
    ApiErrorId,
    count_asset,
    create_class,
    create_in_service_asset,
    create_inventory_run,
    current_asset_version,
    refresh_asset,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_inventory_run_recount_status_cycle(api):
    """PRD §3.6: "When every seeded line has been counted — `found` is non-null
    on all of them — the clerk begins reconciliation, moving the run from
    `COUNTING` to `RECONCILING`; attempting it with any line still uncounted is
    rejected with `ERR_UNCOUNTED_LINES`."
    PRD §3.6: "If discrepancies surface, the clerk sends the run back from
    `RECONCILING` to `COUNTING` for a recount, after which lines may be
    re-counted (upserted) again."

    Design: Difficulty/non_linear_state_machine/inventory_recount_reconciling_cycle
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-400", description="Press",
        acquisition_cost_cents=300000,
    )
    run = create_inventory_run(name="FY26 count", scope_type="ALL")
    assert run["status"] == "COUNTING"

    count_asset(run["id"], asset["id"], found=True, counted_location="PLANT-2")

    reconciling = validate_success(api.begin_reconciliation(run["id"], CLERK), 200)
    assert reconciling["status"] == "RECONCILING"

    counting = validate_success(api.recount_inventory_run(run["id"], CLERK), 200)
    assert counting["status"] == "COUNTING"

    count_asset(run["id"], asset["id"], found=True, counted_location="PLANT-1")

    reconciling2 = validate_success(api.begin_reconciliation(run["id"], CLERK), 200)
    assert reconciling2["status"] == "RECONCILING"

    closed = validate_success(api.close_inventory_run(run["id"], CTRL), 200)
    assert closed["status"] == "CLOSED"


def test_recount_recounts_mismatch_into_match_and_closes(api):
    """PRD §3.6: "Each upsert recomputes the line's `reconciliation_status`:
    still `PENDING` while `found` is null; `MISSING` when `found` is false;
    `MATCHED` when the asset was found and `counted_location` equals the asset's
    `location`; and `LOCATION_MISMATCH` when it was found somewhere else."
    PRD §3.6: "Closing is terminal (`CLOSED`) and clears
    `open_inventory_exception` on the counted assets, recomputed from the
    remaining non-closed runs."

    Design: Difficulty/non_linear_state_machine/inventory_recount_reconciling_cycle
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-400", description="Press",
        acquisition_cost_cents=300000,
    )
    run = create_inventory_run(name="FY26 count", scope_type="ALL")

    first = count_asset(run["id"], asset["id"], found=True,
                        counted_location="PLANT-2")
    assert first["reconciliation_status"] == "LOCATION_MISMATCH"
    assert refresh_asset(asset["id"])["open_inventory_exception"] is True

    validate_success(api.begin_reconciliation(run["id"], CLERK), 200)
    validate_success(api.recount_inventory_run(run["id"], CLERK), 200)

    recount = count_asset(run["id"], asset["id"], found=True,
                          counted_location="PLANT-1")
    assert recount["reconciliation_status"] == "MATCHED"

    validate_success(api.begin_reconciliation(run["id"], CLERK), 200)
    closed = validate_success(api.close_inventory_run(run["id"], CTRL), 200)
    assert closed["matched_count"] == 1
    assert closed["missing_count"] == 0
    assert closed["mismatch_count"] == 0
    assert refresh_asset(asset["id"])["open_inventory_exception"] is False


def test_inventory_line_status_derivation(api):
    """PRD §3.6: "Each upsert recomputes the line's `reconciliation_status`:
    still `PENDING` while `found` is null; `MISSING` when `found` is false;
    `MATCHED` when the asset was found and `counted_location` equals the asset's
    `location`; and `LOCATION_MISMATCH` when it was found somewhere else."
    PRD §3.6: "The run's counters recount the lines by status: `matched_count`
    for `MATCHED` lines, `mismatch_count` for `LOCATION_MISMATCH` lines, and
    `missing_count` for `MISSING` lines **excluding** any whose asset has since
    become `DISPOSED`."
    PRD §3.6: "An asset's `open_inventory_exception` flag is true exactly when
    some line for that asset is `MISSING` or `LOCATION_MISMATCH` in a run that is
    not yet `CLOSED`"

    Design: Corner/calculations/inventory_line_status_derivation
    """
    cls = create_class()
    a1 = create_in_service_asset(cls["id"], asset_tag="I-1", description="One",
                                 acquisition_cost_cents=500000)
    a2 = create_in_service_asset(cls["id"], asset_tag="I-2", description="Two",
                                 acquisition_cost_cents=500000)
    a3 = create_in_service_asset(cls["id"], asset_tag="I-3", description="Three",
                                 acquisition_cost_cents=500000)
    run = create_inventory_run(name="Derivation run", scope_type="ALL")
    assert run["expected_count"] == 3

    l1 = count_asset(run["id"], a1["id"], found=True, counted_location="PLANT-1")
    l2 = count_asset(run["id"], a2["id"], found=True, counted_location="PLANT-9")
    l3 = count_asset(run["id"], a3["id"], found=False)
    assert l1["reconciliation_status"] == "MATCHED"
    assert l2["reconciliation_status"] == "LOCATION_MISMATCH"
    assert l3["reconciliation_status"] == "MISSING"

    after = validate_success(api.get_inventory_run(run["id"], ACCT), 200)
    assert after["expected_count"] == 3
    assert after["matched_count"] == 1
    assert after["mismatch_count"] == 1
    assert after["missing_count"] == 1

    assert refresh_asset(a1["id"])["open_inventory_exception"] is False
    assert refresh_asset(a2["id"])["open_inventory_exception"] is True
    assert refresh_asset(a3["id"])["open_inventory_exception"] is True


def test_damaged_count_auto_opens_impairment_review(api):
    """PRD §3.6: "A `DAMAGED` count on a found asset has a second effect: it
    automatically opens an impairment review with `indicator` equal to `DAMAGE`
    and `source` equal to `INVENTORY`, created by the system itself with
    `created_by_user_id` set to the literal `system` — unless a review is already
    `OPEN` for that asset, in which case no duplicate is created."

    Design: Corner/state_machines/damaged_count_auto_opens_impairment_review
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-095", description="Damaged asset",
        acquisition_cost_cents=500000,
    )
    run = create_inventory_run(name="Damage run", scope_type="ALL")

    line = count_asset(run["id"], asset["id"], found=True,
                       counted_location="PLANT-1", condition="DAMAGED")
    assert line["reconciliation_status"] == "MATCHED", (
        "found at the same location reconciles MATCHED despite DAMAGED"
    )

    reviews, meta = validate_paginated(
        api.list_impairment_reviews(CTRL, params={"asset_id": asset["id"]})
    )
    assert meta["total_count"] == 1
    review = reviews[0]
    assert review["status"] == "OPEN"
    assert review["indicator"] == "DAMAGE"
    assert review["source"] == "INVENTORY"
    assert review["created_by_user_id"] == "system"

    # A second DAMAGED count while that review is still OPEN creates no duplicate.
    count_asset(run["id"], asset["id"], found=True,
                counted_location="PLANT-1", condition="DAMAGED")
    reviews2, meta2 = validate_paginated(
        api.list_impairment_reviews(CTRL, params={"asset_id": asset["id"]})
    )
    assert meta2["total_count"] == 1
    assert reviews2[0]["id"] == review["id"]


def test_location_patch_reconciles_mismatch(api):
    """PRD §3.6: "The same derivation is re-evaluated when a run closes and
    whenever an asset's `location` is edited, so a legitimate location correction
    can turn a mismatch into a match without re-counting."
    PRD §3.6: "a `Controller` closes a `RECONCILING` run — permitted only when
    every seeded line is `MATCHED` **or** its asset is `DISPOSED`"

    Design: Corner/complexity_layers/location_patch_reconciles_mismatch
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-082", description="Moved asset",
        acquisition_cost_cents=500000,
    )
    run = create_inventory_run(name="Move run", scope_type="ALL")
    line = count_asset(run["id"], asset["id"], found=True,
                       counted_location="PLANT-2")
    assert line["reconciliation_status"] == "LOCATION_MISMATCH"
    assert refresh_asset(asset["id"])["open_inventory_exception"] is True

    patched = validate_success(
        api.patch_fixed_asset(
            asset["id"],
            {"expected_asset_version": current_asset_version(asset["id"]),
             "location": "PLANT-2"},
            ACCT,
        ),
        200,
    )
    assert patched["location"] == "PLANT-2"

    lines, _meta = validate_paginated(api.list_run_count_lines(run["id"], ACCT))
    assert lines[0]["reconciliation_status"] == "MATCHED", (
        "the line re-derived to MATCHED with no direct line write"
    )

    validate_success(api.begin_reconciliation(run["id"], CLERK), 200)
    closed = validate_success(api.close_inventory_run(run["id"], CTRL), 200)
    assert closed["matched_count"] == 1
    assert refresh_asset(asset["id"])["open_inventory_exception"] is False


def test_begin_reconciliation_with_uncounted_lines_rejected(api):
    """PRD §3.6: "When every seeded line has been counted — `found` is non-null
    on all of them — the clerk begins reconciliation, moving the run from
    `COUNTING` to `RECONCILING`; attempting it with any line still uncounted is
    rejected with `ERR_UNCOUNTED_LINES`."

    Design: Corner/validations/begin_reconciliation_with_uncounted_lines_rejected
    """
    cls = create_class()
    counted = create_in_service_asset(cls["id"], asset_tag="A-046",
                                      description="Counted",
                                      acquisition_cost_cents=500000)
    create_in_service_asset(cls["id"], asset_tag="A-047",
                            description="Uncounted", acquisition_cost_cents=500000)
    run = create_inventory_run(name="Partial count", scope_type="ALL")
    count_asset(run["id"], counted["id"], found=True, counted_location="PLANT-1")

    resp = api.begin_reconciliation(run["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_UNCOUNTED_LINES, 409)

    after = validate_success(api.get_inventory_run(run["id"], ACCT), 200)
    assert after["status"] == "COUNTING"


def test_close_with_unresolved_items_rejected(api):
    """PRD §3.6: "a `Controller` closes a `RECONCILING` run — permitted only when
    every seeded line is `MATCHED` **or** its asset is `DISPOSED` (an asset
    scrapped as missing via the §3.5 exempt path therefore does not block the
    close) — otherwise the close is rejected with
    `ERR_UNRESOLVED_INVENTORY_ITEMS`."

    Design: Corner/validations/close_with_unresolved_items_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-048", description="Missing asset",
        acquisition_cost_cents=500000,
    )
    run = create_inventory_run(name="Unresolved", scope_type="ALL")
    count_asset(run["id"], asset["id"], found=False)
    validate_success(api.begin_reconciliation(run["id"], CLERK), 200)

    resp = api.close_inventory_run(run["id"], CTRL)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_INVENTORY_ITEMS, 409)

    after = validate_success(api.get_inventory_run(run["id"], ACCT), 200)
    assert after["status"] == "RECONCILING"


def test_count_line_out_of_scope_rejected(api):
    """PRD §3.6: "Creation seeds one count line per in-scope asset whose status
    is `IN_SERVICE` or `FULLY_DEPRECIATED`"
    PRD §3.6: "The upsert is valid only while the run is `COUNTING` — against a
    `RECONCILING` or `CLOSED` run it is rejected with `ERR_RUN_NOT_COUNTING` —
    and only for an asset that was actually seeded into the run, else
    `ERR_ASSET_NOT_IN_SCOPE`."

    Design: Corner/validations/count_line_out_of_scope_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-055", description="Out of scope",
        acquisition_cost_cents=500000, location="PLANT-2",
    )
    run = create_inventory_run(name="Plant 1 only", scope_type="LOCATION",
                               scope_value="PLANT-1")
    assert run["expected_count"] == 0, "the PLANT-2 asset was not seeded"

    resp = api.upsert_count_line(
        run["id"],
        {"asset_id": asset["id"], "found": True, "counted_location": "PLANT-2"},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_ASSET_NOT_IN_SCOPE, 409)


def test_count_upsert_on_reconciling_run_rejected(api):
    """PRD §3.6: "The upsert is valid only while the run is `COUNTING` — against
    a `RECONCILING` or `CLOSED` run it is rejected with `ERR_RUN_NOT_COUNTING`"

    Design: Corner/validations/count_upsert_on_reconciling_run_rejected
    """
    cls = create_class()
    asset = create_in_service_asset(
        cls["id"], asset_tag="A-056", description="Recount gate",
        acquisition_cost_cents=500000,
    )
    run = create_inventory_run(name="Gate run", scope_type="ALL")
    count_asset(run["id"], asset["id"], found=True, counted_location="PLANT-1")
    validate_success(api.begin_reconciliation(run["id"], CLERK), 200)

    resp = api.upsert_count_line(
        run["id"],
        {"asset_id": asset["id"], "found": True, "counted_location": "PLANT-1"},
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_COUNTING, 409)

    lines, _meta = validate_paginated(api.list_run_count_lines(run["id"], ACCT))
    assert lines[0]["reconciliation_status"] == "MATCHED", "line value unchanged"
