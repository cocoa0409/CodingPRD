"""Splitting an order, cancelling one, and the conservation identities that survive both."""

from test_helpers import (
    ApiErrorId,
    SPLITTING_USER_ID,
    assert_government_allocation_ceiling,
    assert_ledger_entry,
    assert_money_conservation,
    build_scenario,
    get_success_data,
    list_ledger_entries,
    new_applicant,
    new_catalog_item,
    new_order,
    order_summary,
    quote,
    read_applicant,
    read_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CASE_MANAGER
from test_helpers.test_users import make_case_manager_headers

SPLITTER = make_case_manager_headers(SPLITTING_USER_ID)


# ==========================================================================
# Pre-tender cancellation conserves money across the four-way partition
# ==========================================================================
def _three_applicant_order_at_intake_fully_collected():
    set_clock("2026-06-01T09:00:00Z")
    catalog = new_catalog_item(visa_type="TOURIST")
    order = new_order(catalog["id"])
    for i, name in enumerate(("Money One", "Money Two", "Money Three")):
        new_applicant(order["id"], full_name=name, date_of_birth=f"199{i}-03-04")
    quoted = quote(order["id"])
    assert quoted["total_quoted_cents"] == 68250
    from test_helpers.fixtures import accept_quote, pay

    pay(order["id"], 68250)
    accept_quote(order["id"])
    return order


def test_pre_tender_cancellation_returns_the_whole_government_stream(api):
    """PRD §3.11: "*The pre-tender variant* runs when `government_tendered_cents` is 0. The
    government refund is the whole of `collected_government_cents` — the pass-through money
    never reached the agency, so all of it comes back. `REFUND` ledger rows with `reason`
    `CANCELLATION_REFUND` are written **immediately**, one per stream, and only for a stream
    whose refund amount is strictly positive."
    PRD §3.11: "The service refund is the order's `collected_service_cents` multiplied by
    that fraction, rounded half up to whole cents."

    Design: Difficulty/compensating_invariant/pre_tender_cancellation_preserves_two_stream_money_conservation
    """
    order = _three_applicant_order_at_intake_fully_collected()

    cancelled = validate_success(api.cancel_order(order["id"], CASE_MANAGER))
    assert cancelled["workflow_status"] == "CANCELLED"

    stored = read_order(order["id"])
    assert stored["collected_government_cents"] == 48000
    assert stored["collected_service_cents"] == 20250
    assert stored["government_tendered_cents"] == 0
    # 48000 government returned in full, plus 20250 * 0.75 = 15187.5 rounded half
    # up to 15188 on the SERVICE stream.
    assert stored["refunded_cents"] == 63188, (
        f"expected 48000 + 15188, got {stored['refunded_cents']}"
    )
    assert stored["payment_status"] == "PARTIALLY_REFUNDED"

    refunds = [r for r in list_ledger_entries(order["id"]) if r["kind"] == "REFUND"]
    assert len(refunds) == 2, f"one REFUND row per stream, got {len(refunds)}"
    for row in refunds:
        assert_ledger_entry(row)
        assert row["reason"] == "CANCELLATION_REFUND"
    assert {r["stream"] for r in refunds} == {"GOVERNMENT", "SERVICE"}


def test_the_compensating_cancellation_leaves_the_money_identity_exact(api):
    """PRD §2.11: "`collected_cents` equals `government_tendered_cents` plus
    `service_earned_cents` plus `refunded_cents` plus `outstanding_cents`."
    PRD §2.11: "First, take the smaller of the refund amount and the order's current
    `outstanding_cents`, and subtract that amount from `outstanding_cents`. Second, subtract
    whatever remains of the refund from `service_earned_cents` — this de-recognises revenue
    the expediter had already booked. Finally add the full refund amount to
    `refunded_cents`."

    Design: Difficulty/compensating_invariant/pre_tender_cancellation_preserves_two_stream_money_conservation
    """
    order = _three_applicant_order_at_intake_fully_collected()

    validate_success(api.cancel_order(order["id"], CASE_MANAGER))

    stored = read_order(order["id"])
    assert stored["collected_cents"] == 68250
    assert stored["service_earned_cents"] == 0, (
        "nothing had been recognised as revenue before the cancellation"
    )
    assert stored["outstanding_cents"] == 5062, (
        f"68250 collected less the 63188 drawn for the refund, got {stored['outstanding_cents']}"
    )
    assert_money_conservation(stored)
    assert_government_allocation_ceiling(stored)

    summary = order_summary(order["id"])
    assert summary["conservation_ok"] is True


# ==========================================================================
# The split partition
# ==========================================================================
def test_split_partitions_both_streams_and_conserves_money_across_the_pair(api):
    """PRD §3.12: "The government transfer is the parent's `collected_government_cents`
    multiplied by the moved count and divided by the pre-move count, rounded half up to
    whole cents; the service transfer is the parent's `collected_service_cents` treated the
    same way. The two streams are rounded **independently** and are never netted against
    each other."
    PRD §2.11: "Every `TRANSFER_OUT` row written on the parent has a mirror `TRANSFER_IN`
    row on the child with an identical `stream` and an identical `amount_cents`, so the two
    orders' `collected_cents` figures together equal what the parent alone held before the
    split."
    PRD §3.12: "Finally **both** orders re-run their government and service pricing against
    their own traveller sets, with the promotional discount component treated as 0.00 — a
    promotion never survives a split — overwriting `government_fee_quoted_cents`,
    `service_fee_quoted_cents`, `total_quoted_cents`, `discount_pct_applied` and
    `handling_fee_waived` on each."

    Design: Corner/calculations/corner_split_money_partition_conserves_across_parent_and_child
    """
    scenario = build_scenario("intake", applicant_count=3, visa_type="PASSPORT_RENEWAL")
    parent_id = scenario["order_id"]
    moved_id = scenario["applicant_ids"][2]
    assert scenario["order"]["collected_cents"] == 68250

    child = get_success_data(api.split_order(parent_id, {"applicant_ids": [moved_id]}, SPLITTER))

    assert child["parent_order_id"] == parent_id
    assert child["collected_government_cents"] == 16000, "48000 * 1/3"
    assert child["collected_service_cents"] == 6750, "20250 * 1/3"
    assert child["collected_cents"] == 22750
    assert child["outstanding_cents"] == 22750
    assert child["total_quoted_cents"] == 26500, "re-priced for one traveller"

    parent = read_order(parent_id)
    assert parent["collected_cents"] == 45500
    assert parent["service_earned_cents"] == 1500, "the split administration charge"
    assert parent["outstanding_cents"] == 44000
    assert parent["total_quoted_cents"] == 50000, "re-priced for two travellers"
    assert parent["applicant_count"] == 2
    assert read_applicant(moved_id)["order_id"] == child["id"]

    assert parent["collected_cents"] + child["collected_cents"] == 68250
    assert_money_conservation(parent)
    assert_money_conservation(child)

    _rows, meta = validate_paginated(api.list_orders(ADMIN, {"parent_order_id": parent_id}))
    assert meta["total_count"] == 1, f"exactly one child order, got {meta['total_count']}"


def test_split_refuses_a_traveller_who_is_not_complete(api):
    """PRD §3.12: "Every named traveller must belong to this order and carry
    `readiness_status` `COMPLETE`, and at least one traveller must remain on the parent, or
    the request is `ERR_APPLICANT_NOT_READY`."

    Design: Corner/errors/corner_error_applicant_not_ready_on_split
    """
    scenario = build_scenario(
        "intake", applicant_count=2, visa_type="PASSPORT_RENEWAL", make_complete=False
    )
    parent_id = scenario["order_id"]
    second_id = scenario["applicant_ids"][1]
    assert read_applicant(second_id)["readiness_status"] == "PENDING"

    resp = api.split_order(parent_id, {"applicant_ids": [second_id]}, SPLITTER)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_READY.value)

    assert read_applicant(second_id)["order_id"] == parent_id
    assert read_order(parent_id)["applicant_count"] == 2
    _rows, meta = validate_paginated(api.list_orders(ADMIN, {"parent_order_id": parent_id}))
    assert meta["total_count"] == 0, "no child order is created by a refused split"


def test_split_refuses_a_transfer_override_that_misses_the_computed_total(api):
    """PRD §3.12: "Their sum is the transfer total, and when `transfer_cents_override` is
    supplied it must equal exactly that sum or the request is `ERR_SPLIT_PARTITION_MISMATCH`."

    Design: Corner/errors/corner_error_split_transfer_override_mismatch
    """
    scenario = build_scenario("intake", applicant_count=2, visa_type="PASSPORT_RENEWAL")
    parent_id = scenario["order_id"]
    second_id = scenario["applicant_ids"][1]
    assert scenario["order"]["collected_cents"] == 50000

    # The computed transfer is 32000 * 1/2 = 16000 government plus 18000 * 1/2 =
    # 9000 service, so the override must be exactly 25000.
    resp = api.split_order(
        parent_id,
        {"applicant_ids": [second_id], "transfer_cents_override": 24000},
        SPLITTER,
    )
    validate_error(resp, ApiErrorId.ERR_SPLIT_PARTITION_MISMATCH.value)

    parent = read_order(parent_id)
    assert parent["collected_cents"] == 50000
    assert parent["applicant_count"] == 2
    assert read_applicant(second_id)["order_id"] == parent_id
    _rows, meta = validate_paginated(api.list_orders(ADMIN, {"parent_order_id": parent_id}))
    assert meta["total_count"] == 0
