"""State-machine transitions, usage report, list filters, and derived counts.

Corner queue B: state_machines, calculations, endpoints,
cross_cutting_complexity_layers (derived_field_reconciliation).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_member, create_item, add_copy, set_clock, ops_run, checkout,
    return_loan, create_reservation, get_item, get_copy, get_reservation,
    item_version, assert_same_instant,
    return_loan_payload, TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


# =========================================================================== #
# Corner/state_machines/return_already_returned_loan_rejected
# =========================================================================== #
def test_return_already_returned_loan_rejected(api):
    """Returning a loan that is already RETURNED is rejected with
    ERR_LOAN_NOT_ACTIVE.

    PRD §3.5: "Return is permitted only when the loan is `ACTIVE` or `OVERDUE`
    (otherwise `ERR_LOAN_NOT_ACTIVE`)."

    Design: Corner/state_machines/return_already_returned_loan_rejected
    """
    member = create_member()
    item = create_item(name="Vise", category="TOOL", replacement_value_cents=5000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="V-1")
    set_clock("2026-03-01T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    return_loan(loan["id"], "GOOD")
    res = api_client.return_loan(loan["id"], return_loan_payload("GOOD"), COORD)
    validate_error(res, "ERR_LOAN_NOT_ACTIVE")


# =========================================================================== #
# Corner/state_machines/new_loan_starts_active_initial_state
# =========================================================================== #
def test_new_loan_starts_active_with_computed_due_date(api):
    """A freshly created loan starts ACTIVE with renewals_used=0 and due_date =
    checked_out_at + loan_period_days.

    PRD §3.4: "`renewals_used` starts at 0, the loan's `status` becomes `ACTIVE`,
    and `checked_out_by_volunteer_id` records the operator's `X-User-ID`."
    PRD §3.4: "`due_date` is computed as `checked_out_at` plus the item's
    `loan_period_days`, ..."

    Design: Corner/state_machines/new_loan_starts_active_initial_state
    """
    member = create_member()
    item = create_item(name="Clamp", category="TOOL", replacement_value_cents=2000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="CL-1")
    set_clock("2026-03-01T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    assert loan["status"] == "ACTIVE"
    assert loan["renewals_used"] == 0
    assert_same_instant(loan["due_date"], "2026-03-08T00:00:00Z", "initial due_date")


# =========================================================================== #
# Corner/state_machines/reservation_expiry_via_ops_run
# =========================================================================== #
def test_reservation_expires_and_releases_copy_via_ops_run(api):
    """Housekeeping past window_end expires a PENDING reservation and releases its
    copy from RESERVED back to AVAILABLE.

    PRD §3.3: "expiry, which occurs during housekeeping once the logical clock
    reaches or passes `window_end` on a still-unfulfilled reservation, moves it to
    `EXPIRED`."
    PRD §3.3: "In both cases the assigned copy is released from `RESERVED` back to
    `AVAILABLE`, the item's `reserved_count`, `available_copies_count`, and
    `version` are recomputed, ..."

    Design: Corner/state_machines/reservation_expiry_via_ops_run
    """
    member = create_member()
    item = create_item(name="Spade", category="OUTDOOR", replacement_value_cents=2500,
                       loan_period_days=3, daily_late_fee_cents=200)
    copy = add_copy(item["id"], asset_tag="SP-1")
    set_clock("2026-03-01T00:00:00Z")
    reservation = create_reservation(member["id"], item["id"],
                                     "2026-03-05T00:00:00Z", "2026-03-07T00:00:00Z")
    set_clock("2026-03-08T00:00:00Z")
    ops_run()
    assert get_reservation(reservation["id"])["status"] == "EXPIRED"
    assert get_copy(copy["id"])["availability_status"] == "AVAILABLE"


# =========================================================================== #
# Corner/calculations/usage_report_counts_active_and_overdue
# =========================================================================== #
def test_usage_report_counts_one_active_loan(api):
    """With one ACTIVE loan, the usage report reports active_loans=1, overdue_loans=0.

    PRD §3.9: "`active_loans`, the count of loans whose status is `ACTIVE` or
    `OVERDUE`; `overdue_loans`, the count of loans whose status is `OVERDUE`; ..."

    Design: Corner/calculations/usage_report_counts_active_and_overdue
    """
    member = create_member()
    item = create_item(name="Level", category="TOOL", replacement_value_cents=3000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="LV-1")
    set_clock("2026-03-01T00:00:00Z")
    checkout(member["id"], copy["id"], item["id"])
    report = validate_success(api_client.get_usage_report(COORD), 200)
    assert report["active_loans"] == 1
    assert report["overdue_loans"] == 0


# =========================================================================== #
# Corner/endpoints/list_copies_of_item_reverse_reachability
# =========================================================================== #
def test_list_copies_of_item_reverse_lookup(api):
    """GET /library/items/{id}/copies returns the item's copies as a paginated
    array (reverse lookup for ItemCopy.item_id).

    PRD §3.2: "The `item_id` linking a copy to its title is established at
    creation, and the copies of an item can be listed for reverse lookup."

    Design: Corner/endpoints/list_copies_of_item_reverse_reachability
    """
    item = create_item(name="Planer", category="TOOL", replacement_value_cents=6000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="PL-1")
    resp = api_client.list_copies(item["id"], COORD, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert any(c["id"] == copy["id"] for c in data), "listed copies must include the created copy"
    assert "total_count" in meta and "has_more" in meta


# =========================================================================== #
# Corner/endpoints/list_loans_by_member_filter
# =========================================================================== #
def test_list_loans_filtered_by_member(api):
    """GET /library/loans?member_id={id} returns that member's loan.

    PRD §2.3: "Unless a specific endpoint says otherwise, every list endpoint
    returns resources sorted by their `created_at` timestamp in ascending order."

    Design: Corner/endpoints/list_loans_by_member_filter
    """
    member = create_member()
    item = create_item(name="Bit", category="TOOL", replacement_value_cents=1200,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="BT-1")
    set_clock("2026-03-01T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    data, _meta = validate_paginated(
        api_client.list_loans(COORD, params={"member_id": member["id"]}))
    assert any(ln["id"] == loan["id"] for ln in data), "member's loan must be listed"


# =========================================================================== #
# Corner/cross_cutting_complexity_layers/derived_available_count_after_checkout
# =========================================================================== #
def test_derived_counts_after_checkout(api):
    """After checking out the only copy, available_copies_count=0 and on_loan_count=1.

    PRD §2.6: "`available_copies_count` is the number of copies that are
    simultaneously `AVAILABLE` on the availability axis and `GOOD` on the
    condition axis."
    PRD §2.6: "`on_loan_count` is the number of copies whose `availability_status`
    is `ON_LOAN`."

    Design: Corner/cross_cutting_complexity_layers/derived_available_count_after_checkout
    """
    member = create_member()
    item = create_item(name="Chisel", category="TOOL", replacement_value_cents=1800,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="CH-1")
    set_clock("2026-03-01T00:00:00Z")
    checkout(member["id"], copy["id"], item["id"])
    got = get_item(item["id"])
    assert got["available_copies_count"] == 0
    assert got["on_loan_count"] == 1
