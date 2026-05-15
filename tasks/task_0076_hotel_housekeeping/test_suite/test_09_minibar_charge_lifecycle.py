"""Minibar consumption: creation, line-item validation, posting,
sum-then-round taxation, and the immutability invariant (PRD §3.11).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    MINIBAR_TAX_RATE,
    TEST_USERS,
    assert_minibar_charge_integrity,
    assert_minibar_consumption,
    create_minibar_consumption_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    create_archived_minibar_item,
    create_minibar_consumption,
    create_minibar_item,
    create_room,
    post_consumption,
    setup_consumption_in_state,
    setup_consumption_two_25c_items,
)


# ===========================================================================
# Line-item validation (PRD §3.11)
# ===========================================================================
def test_empty_line_items_rejected(api):
    """PRD §3.11: "line_items must be non-empty, every quantity must be
    at least one, and the same minibar_item_id must not appear twice
    in a single record. Violations are rejected with
    ERR_INVALID_LINE_QUANTITY for empty arrays or sub-one quantities."
    """
    room = create_room()
    payload = create_minibar_consumption_payload(
        room_id=room["id"], source_type="GUEST_SELF_REPORT",
        line_items=[],
    )
    res = api.create_minibar_consumption(
        payload, TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_LINE_QUANTITY.value)


def test_zero_quantity_line_item_rejected(api):
    """PRD §3.11: "ERR_INVALID_LINE_QUANTITY for empty arrays or
    sub-one quantities."
    """
    room = create_room()
    item = create_minibar_item()
    payload = create_minibar_consumption_payload(
        room_id=room["id"], source_type="GUEST_SELF_REPORT",
        line_items=[{"minibar_item_id": item["id"], "quantity": 0}],
    )
    res = api.create_minibar_consumption(
        payload, TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_LINE_QUANTITY.value)


def test_duplicate_minibar_item_in_lines_rejected(api):
    """PRD §3.11: "ERR_DUPLICATE_MINIBAR_LINE_ITEM for repeated SKUs."
    """
    room = create_room()
    item = create_minibar_item()
    payload = create_minibar_consumption_payload(
        room_id=room["id"], source_type="GUEST_SELF_REPORT",
        line_items=[
            {"minibar_item_id": item["id"], "quantity": 1},
            {"minibar_item_id": item["id"], "quantity": 2},
        ],
    )
    res = api.create_minibar_consumption(
        payload, TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_MINIBAR_LINE_ITEM.value)


def test_archived_item_in_lines_rejected(api):
    """PRD §3.11: "A line that references an archived item is rejected
    with ERR_MINIBAR_ITEM_ARCHIVED."
    """
    room = create_room()
    archived = create_archived_minibar_item()
    payload = create_minibar_consumption_payload(
        room_id=room["id"], source_type="GUEST_SELF_REPORT",
        line_items=[{"minibar_item_id": archived["id"], "quantity": 1}],
    )
    res = api.create_minibar_consumption(
        payload, TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_MINIBAR_ITEM_ARCHIVED.value)


# ===========================================================================
# Charge calculation — sum-then-round (PRD §3.11)
# ===========================================================================
def test_sum_then_round_invariant_for_two_25c_lines(api):
    """PRD §3.11: "computes tax_cents as the gross amount multiplied by
    the minibar tax rate of 0.10 and rounded half-up to a whole cent
    on that single product (per-line tax-then-sum is incorrect because
    each line's tax would be rounded independently)."

    Two 25¢ items → gross=50, tax = round_half_up(50*0.10) = 5, posted
    = 55. The wrong "round-per-line then sum" approach yields
    round(2.5)+round(2.5) = 3+3 = 6, posted = 56 — which the
    sum-then-round rule forbids.
    """
    room, items, consumption = setup_consumption_two_25c_items()
    assert consumption["status"] == "PENDING"
    posted = post_consumption(consumption["id"])
    assert posted["status"] == "POSTED"
    assert posted["gross_amount_cents"] == 50
    assert posted["tax_cents"] == 5, (
        "PRD §3.11: tax computed on the SUM (round_half_up(50*0.10)=5), "
        "not per line (which would give 6)."
    )
    assert posted["posted_amount_cents"] == 55
    assert_minibar_charge_integrity(posted)


def test_posted_amount_immutable_after_post(api):
    """PRD §3.11: "Once posted, gross_amount_cents, tax_cents, and
    posted_amount_cents are immutable."

    PRD §2.8: "Once a minibar consumption advances past PENDING, its
    gross_amount_cents, tax_cents, and posted_amount_cents are
    immutable, so the folio always reconciles exactly to the moment of
    posting."

    Claim: re-fetching a POSTED consumption returns the same
    gross/tax/posted as set at posting.
    """
    room, items, posted = setup_consumption_in_state(
        target="POSTED", unit_price_cents=100, line_count=3,
        quantity_each=2,
    )
    # Expected: 3 lines × 2 qty × 100¢ = 600 gross, tax = 60,
    # posted = 660.
    assert posted["gross_amount_cents"] == 600
    assert posted["tax_cents"] == 60
    assert posted["posted_amount_cents"] == 660
    res = api.get_minibar_consumption(
        posted["id"], TEST_USERS["frontdesk_headers"],
    )
    again = validate_success(res)
    assert again["gross_amount_cents"] == 600
    assert again["tax_cents"] == 60
    assert again["posted_amount_cents"] == 660


def test_post_appends_minibar_consumption_post_audit_entry(api):
    """PRD §3.11: "A MINIBAR_CONSUMPTION_POST audit entry is appended."
    """
    from test_helpers.fixtures import list_audit_entries_for_subject
    room, items, posted = setup_consumption_in_state(target="POSTED")
    audit = list_audit_entries_for_subject(
        posted["id"], action_type="MINIBAR_CONSUMPTION_POST",
    )
    assert len(audit) >= 1


# ===========================================================================
# State transitions (PRD §3.11)
# ===========================================================================
def test_double_post_rejected(api):
    """PRD §5: "Operation requires MinibarConsumption.status == PENDING"
    → ERR_CONSUMPTION_NOT_PENDING.

    PRD §3.11: "Two simultaneous posts on the same PENDING consumption
    serialise on MinibarConsumption.status: the first wins, the second
    receives ERR_CONSUMPTION_NOT_PENDING."

    Sequential double-post (not race) — equally must yield
    ERR_CONSUMPTION_NOT_PENDING on the second call.
    """
    room, items, posted = setup_consumption_in_state(target="POSTED")
    res = api.post_minibar_consumption(
        posted["id"], TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CONSUMPTION_NOT_PENDING.value)


def test_create_consumption_guest_self_report_with_task_id_path(api):
    """PRD §3.11: "an optional cleaning_task_id linking to the
    originating cleaning task (which must be null exactly when
    source_type is GUEST_SELF_REPORT)."

    Claim: a GUEST_SELF_REPORT with a cleaning_task_id is rejected as
    ERR_INVALID_REQUEST (generic shape validation per PRD §2.6's
    structural fallback).
    """
    room = create_room()
    item = create_minibar_item()
    payload = create_minibar_consumption_payload(
        room_id=room["id"], source_type="GUEST_SELF_REPORT",
        line_items=[{"minibar_item_id": item["id"], "quantity": 1}],
        cleaning_task_id="00000000-0000-0000-0000-000000000000",
    )
    res = api.create_minibar_consumption(
        payload, TEST_USERS["frontdesk_headers"],
    )
    # PRD §2.6 names ERR_INVALID_REQUEST as the structural-shape error;
    # either that or ERR_TASK_NOT_FOUND is faithful (path-existence
    # check on the FK might fire first per priority 4).
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(res, [
        ApiErrorId.ERR_INVALID_REQUEST.value,
        ApiErrorId.ERR_TASK_NOT_FOUND.value,
    ])
