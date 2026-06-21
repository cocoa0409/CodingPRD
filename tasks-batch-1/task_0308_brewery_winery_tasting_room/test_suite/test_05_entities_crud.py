"""Entity creation, defaults, computed fields, not-found, and ledger immutability.

Translates the non-stub `entities` corners and the immediate-consistency corner.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_winery_payload, create_batch_payload, create_product_payload,
    assert_winery, assert_product, assert_ledger_entry,
    create_winery, create_batch, create_batch_in_bottling, create_product,
    bottle_run, NON_EXISTENT_UUID, TEST_USERS,
)

CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["cellar_manager_headers"]


def test_create_winery_returns_201_with_defaults(api):
    """PRD §3.1: "A new winery starts with `status` `ACTIVE` and all of its
    accounting balances at zero: `bulk_volume_gallons` ... `excise_tax_owed_cents`
    (cumulative excise accrued, in cents), and `loyalty_point_liability`".
    PRD §2.4: "The `version` field begins at 1 on creation".

    POST /wineries returns 201 with status ACTIVE, version 1, balances 0.

    Design: Corner/entities/create_winery_returns_201_with_defaults
    """
    res = api.create_winery(create_winery_payload(name="Fresh Co", ttb_permit_number="FR-1",
                                                  home_state_code="OR"), CO)
    winery = validate_success(res, 201)
    assert_winery(winery)
    assert winery["status"] == "ACTIVE", winery["status"]
    assert winery["version"] == 1, winery["version"]
    assert winery["excise_tax_owed_cents"] == 0, winery["excise_tax_owed_cents"]
    assert winery["loyalty_point_liability"] == 0, winery["loyalty_point_liability"]


def test_create_batch_missing_required_volume_rejected(api):
    """PRD §2.9: "and finally, lowest priority, field-level request validity
    (`ERR_INVALID_REQUEST`)."
    PRD §3.2: "creates one against a `winery_id`, with a `lot_code` unique within
    that winery, a `beverage_class` ... the `volume_in_gallons` charged into the
    batch at start, and the `abv_percent`".

    POST /batches without volume_in_gallons -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_batch_missing_required_volume_rejected
    """
    winery = create_winery(name="B Co", ttb_permit_number="B-1")
    payload = create_batch_payload(winery["id"], beverage_class="WINE", abv_percent=13.5)
    del payload["volume_in_gallons"]
    res = api.create_batch(payload, CM)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_product_is_age_restricted_defaults_true(api):
    """PRD §3.4: "an `is_age_restricted` flag that defaults to true and gates the
    age checks at point of sale and shipment. A new product is born `DRAFT`".

    POST /products omitting is_age_restricted -> is_age_restricted true, status DRAFT.

    Design: Corner/entities/product_is_age_restricted_default_true
    """
    winery = create_winery(name="D Co", ttb_permit_number="D-1")
    batch = create_batch(winery["id"])
    res = api.create_product(
        create_product_payload(winery["id"], batch["id"], sku="S1"), CM)
    product = validate_success(res, 201)
    assert product["is_age_restricted"] is True, product["is_age_restricted"]
    assert product["status"] == "DRAFT", product["status"]


def test_product_free_bottles_after_bottling(api):
    """PRD §3.4: "`free_bottles` is always `on_hand_bottles` minus `allocated_bottles`
    — the bottles sellable outside any allocation."
    PRD §3.3: "the product's `on_hand_bottles` increases by `requested_bottles`."

    After bottling 40 with no allocation: on_hand 40, allocated 0, free 40.

    Design: Corner/entities/product_computed_free_bottles_correct_after_bottling
    """
    winery = create_winery(name="F Co", ttb_permit_number="F-1")
    batch = create_batch_in_bottling(winery["id"])
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 40)
    p = get_success_data(api.get_product(product["id"], CM))
    assert p["on_hand_bottles"] == 40, p["on_hand_bottles"]
    assert p["allocated_bottles"] == 0, p["allocated_bottles"]
    assert p["free_bottles"] == 40, p["free_bottles"]


def test_get_nonexistent_winery_returns_404(api):
    """PRD §2.6: "a path that names a resource that does not exist is rejected with
    `ERR_NOT_FOUND` (HTTP 404)".

    GET /wineries/{bogus-uuid} -> ERR_NOT_FOUND.

    Design: Corner/entities/get_nonexistent_winery_returns_404
    """
    res = api.get_winery(NON_EXISTENT_UUID, CO)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_ledger_entry_immutable_no_version_field(api):
    """PRD §2.4: "A `ComplianceLedgerEntry` is an immutable audit event: it carries
    only an `id` and a `created_at`. It has no `updated_at` and no `version`,
    because once booked it is never modified."
    PRD §3.3: "Two compliance ledger entries are appended for the run: one of
    `entry_type` `BOTTLING_REMOVAL` and one of `entry_type` `EXCISE_ACCRUAL`".

    After a bottling run, GET /ledger-entries lists BOTTLING_REMOVAL + EXCISE_ACCRUAL
    rows for the winery, each with id + created_at only (no version).

    Design: Corner/entities/ledger_entry_immutable_no_version_field
    """
    winery = create_winery(name="L Co", ttb_permit_number="L-1")
    batch = create_batch_in_bottling(winery["id"])
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 50)

    data, meta = validate_paginated(api.list_ledger_entries(CO, params={"winery_id": winery["id"]}))
    types = {e["entry_type"] for e in data}
    assert "BOTTLING_REMOVAL" in types, types
    assert "EXCISE_ACCRUAL" in types, types
    for entry in data:
        assert_ledger_entry(entry)


def test_immediate_inventory_visible_in_same_read(api):
    """PRD §2.5: "Many operations mutate more than one resource in a single,
    immediate, all-or-nothing step, and the system keeps every affected balance
    reconciled before the response is returned."
    PRD §3.3: "the product's `on_hand_bottles` increases by `requested_bottles`."

    A bottling run of 30 is visible on the very next GET /products/{id}: on_hand 30.

    Design: Corner/consistency_model/immediate_inventory_visible_in_same_read
    """
    winery = create_winery(name="Im Co", ttb_permit_number="IM-1")
    batch = create_batch_in_bottling(winery["id"])
    product = create_product(winery["id"], batch["id"], sku="S1")
    bottle_run(batch["id"], product["id"], 30)
    p = get_success_data(api.get_product(product["id"], CM))
    assert p["on_hand_bottles"] == 30, p["on_hand_bottles"]
