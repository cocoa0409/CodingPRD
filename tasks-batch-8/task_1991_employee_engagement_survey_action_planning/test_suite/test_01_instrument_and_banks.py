"""Instrument lifecycle: item banks, survey items, retirement cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_item_bank,
    assert_survey_item,
    configure_cycle,
    get_success_data,
    make_active_bank,
    make_cycle,
    make_employee,
    make_unit,
    pin_items,
    api_client,
    close_cycle,
    open_cycle,
    publish_cycle,
    archive_cycle,
    score_cycle,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

HR_ADMIN = TEST_USERS["hr_admin_headers"]
PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]


def test_create_item_bank_ignores_client_supplied_system_fields(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix."
    PRD §2.4: "`version` is an integer that starts at 1 and increments by
    exactly 1 on every mutation of the resource"

    Design: Corner/entities/system_fields_input_ignored_on_create
    """
    resp = api.create_item_bank(
        {
            "name": "SysFields",
            "framework": "EWI",
            "id": "client-forged",
            "created_at": "1999-01-01T00:00:00Z",
            "version": 42,
        },
        HR_ADMIN,
    )
    data = validate_success(resp, 201)
    assert_item_bank(data)
    assert data["id"] != "client-forged", "server must mint its own UUID id"
    assert data["version"] == 1, (
        f"version starts at 1; client-sent 42 must be ignored, got {data['version']}"
    )
    assert data["created_at"] != "1999-01-01T00:00:00Z"
    assert data["status"] == "DRAFT"


def test_survey_item_weight_out_of_range_rejected(api):
    """PRD §2.11: "A survey item's `weight` is a positive decimal with exactly
    one fractional digit, at least 0.1 and at most 5.0."
    PRD §2.8: "Request-shape validation runs first: required body fields
    present, field types valid, enum members legal, and numeric ranges honored
    — failures yield `ERR_VALIDATION` (HTTP 400)"

    Design: Corner/entities/survey_item_weight_out_of_range_rejected
    """
    bank = get_success_data(
        api.create_item_bank({"name": "Weight Bank", "framework": "CUSTOM"}, HR_ADMIN)
    )
    resp_bad = api.add_survey_item(
        bank["id"], {"item_code": "W-BAD", "dimension": "PURPOSE", "weight": 6.0}, HR_ADMIN
    )
    validate_error(resp_bad, ApiErrorId.ERR_VALIDATION)

    resp_ok = api.add_survey_item(
        bank["id"], {"item_code": "W-MAX", "dimension": "PURPOSE", "weight": 5.0}, HR_ADMIN
    )
    item = validate_success(resp_ok, 201)
    assert_survey_item(item)
    assert item["weight"] == pytest.approx(5.0), "5.0 is the inclusive upper bound"


def test_duplicate_item_code_scoped_to_bank(api):
    """PRD §3.1: "Each survey item is created under a bank (the owning bank is
    identified by the request, and the item's `bank_id` records it) with a
    stable `item_code` such as EWI-01 that must be unique within its bank"
    PRD §3.1: "a duplicate `item_code` within one bank is rejected with
    `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/duplicate_item_code_within_bank_rejected
    """
    bank1 = get_success_data(
        api.create_item_bank({"name": "Dup Bank 1", "framework": "EWI"}, HR_ADMIN)
    )
    bank2 = get_success_data(
        api.create_item_bank({"name": "Dup Bank 2", "framework": "EWI"}, HR_ADMIN)
    )
    first = api.add_survey_item(
        bank1["id"], {"item_code": "EWI-01", "dimension": "PURPOSE", "weight": 1.0}, HR_ADMIN
    )
    validate_success(first, 201)

    resp_dup = api.add_survey_item(
        bank1["id"], {"item_code": "EWI-01", "dimension": "GROWTH", "weight": 2.0}, HR_ADMIN
    )
    validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE)

    resp_cross = api.add_survey_item(
        bank2["id"], {"item_code": "EWI-01", "dimension": "GROWTH", "weight": 2.0}, HR_ADMIN
    )
    item = validate_success(resp_cross, 201)
    assert item["item_code"] == "EWI-01", "uniqueness scope is the bank, not the tenant"


def test_bank_retire_refused_while_referencing_cycle_configured(api):
    """PRD §3.1: "Retirement is refused while any survey cycle built on this
    bank sits in `CONFIGURED`, `OPEN`, or `SCORING` status — an in-flight cycle
    keeps its instrument alive."
    PRD §2.8: "an action that the target resource's current state does not
    permit is rejected with `ERR_INVALID_STATE` (HTTP 409), so an illegal
    transition always surfaces as a state error rather than being masked by a
    business rule."
    PRD §3.5: "an outstanding plan blocks archival with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/bank_retire_blocked_by_open_cycle
    """
    bank, items = make_active_bank("RetireBlock")
    set_clock("2026-09-01T00:00:00Z")
    cycle = make_cycle(bank["id"], label="Blocking Cycle")
    pin_items(cycle["id"], items)
    cycle = configure_cycle(cycle["id"])
    assert cycle["status"] == "CONFIGURED"

    resp = api.retire_item_bank(bank["id"], HR_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    bank_after = get_success_data(api.get_item_bank(bank["id"], HR_ADMIN))
    assert bank_after["status"] == "ACTIVE", "refused retirement leaves the bank ACTIVE"


def test_bank_retire_after_cycle_archived_cascades_items(api):
    """PRD §3.1: "When retirement succeeds, every item of the bank still in
    `ACTIVE` status flips to `RETIRED` alongside it, and the bank's `version`
    increments by 1."
    PRD §3.1: "Retirement is refused while any survey cycle built on this
    bank sits in `CONFIGURED`, `OPEN`, or `SCORING` status — an in-flight cycle
    keeps its instrument alive."

    Design: Difficulty/cross_entity_state_dependency/bank_retire_blocked_by_open_cycle
    """
    bank, items = make_active_bank("RetireOk")
    unit = make_unit("RetireUnit", "mgr-ret")
    make_employee(unit["id"], "RET-001")
    set_clock("2026-09-01T00:00:00Z")
    cycle = make_cycle(bank["id"], label="Archiving Cycle")
    pin_items(cycle["id"], items)
    cycle = configure_cycle(cycle["id"])
    cycle = open_cycle(cycle["id"])
    cycle = close_cycle(cycle["id"])
    cycle = score_cycle(cycle["id"])
    cycle = publish_cycle(cycle["id"])
    cycle = archive_cycle(cycle["id"])
    assert cycle["status"] == "ARCHIVED"

    resp = api.retire_item_bank(bank["id"], HR_ADMIN)
    retired = validate_success(resp, 200)
    assert_item_bank(retired)
    assert retired["status"] == "RETIRED"

    items_after, _meta = validate_paginated(
        api.list_survey_items(bank["id"], HR_ADMIN)
    )
    assert len(items_after) == 3
    for item in items_after:
        assert item["status"] == "RETIRED", (
            f"item {item['item_code']} must cascade ACTIVE -> RETIRED with the bank"
        )
