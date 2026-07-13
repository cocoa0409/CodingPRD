"""Compensating invariants, optimistic concurrency, dues-invoice settlement,
pagination, and FK reverse-reachability.

Translates queue A (Difficulty) compensating_invariant instances and queue B
(Corner) instances from the endpoints, cross_cutting, and consistency_model sections.
"""
import test_helpers as th
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId


# --------------------------------------------------------------------------- #
# compensating_invariant (queue A) — weekly reservation credits
# --------------------------------------------------------------------------- #
def _weekly_member_with_request():
    ctx = th.setup_active_basic_member("SAIL")  # reservations_per_week = 4
    m = ctx["member_id"]
    th.set_clock("2026-05-04T08:00:00Z")
    r1 = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    return ctx, r1["id"]


def test_weekly_credits_decrement_on_confirm(api, member_hdr):
    """PRD §3.4: "`reservations_remaining_this_week` is the tier's weekly allowance
    minus that used count, never dropping below zero."
    PRD §3.3: "the member's weekly usage is recomputed to reflect the newly counted
    reservation."

    Design: Difficulty/compensating_invariant/ci_weekly_reservation_credits_confirm_cancel
    """
    ctx, r1 = _weekly_member_with_request()
    m = ctx["member_id"]
    th.confirm_reservation(m, r1)
    member = th.get_member(m)
    assert member["reservations_used_this_week"] == 1
    assert member["reservations_remaining_this_week"] == 3
    assert member["reservations_used_this_week"] + member["reservations_remaining_this_week"] == 4


def test_weekly_credits_restored_on_cancel(api, member_hdr):
    """PRD §3.4: "Across a confirm-then-cancel pair the used and remaining counts always
    sum back to the tier's weekly allowance."

    Design: Difficulty/compensating_invariant/ci_weekly_reservation_credits_confirm_cancel
    """
    ctx, r1 = _weekly_member_with_request()
    m = ctx["member_id"]
    th.confirm_reservation(m, r1)
    api.cancel_reservation(r1, member_hdr(m))
    member = th.get_member(m)
    assert member["reservations_used_this_week"] == 0
    assert member["reservations_remaining_this_week"] == 4
    assert member["reservations_used_this_week"] + member["reservations_remaining_this_week"] == 4


# --------------------------------------------------------------------------- #
# compensating_invariant (queue A) — fee ledger assess/waive
# --------------------------------------------------------------------------- #
def _member_with_assessed_damage_fee():
    ctx = th.setup_active_basic_member("SAIL")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.assessed_damage_fee(r["id"], b1, "MODERATE", 30000)  # single 30000 DAMAGE fee
    fee = th.find_fees(member_id=m, fee_type="DAMAGE")[0]
    return m, fee["id"]


def test_fee_ledger_outstanding_before_waive(api):
    """PRD §3.6: "`outstanding_fees_cents` is the sum of `amount_cents` over their fees
    still `ASSESSED`, `waived_fees_cents` the sum over their `WAIVED` fees, and
    `paid_fees_cents` the sum over their `PAID` fees; those three partitions always add
    up to the total of all the member's fee amounts."

    Design: Difficulty/compensating_invariant/ci_fee_ledger_assess_waive
    """
    m, fee_id = _member_with_assessed_damage_fee()
    member = th.get_member(m)
    assert member["outstanding_fees_cents"] == 30000
    assert member["waived_fees_cents"] == 0
    th.assert_fee_ledger_conserved(member, 30000)


def test_fee_ledger_conserved_after_waive(api):
    """PRD §3.6: "`DockStaff` may waive an `ASSESSED` fee, addressed by its `fee_id`,
    moving it to `WAIVED`".
    PRD §3.6: "those three partitions always add up to the total of all the member's
    fee amounts."

    Design: Difficulty/compensating_invariant/ci_fee_ledger_assess_waive
    """
    m, fee_id = _member_with_assessed_damage_fee()
    th.waive_fee(fee_id)
    member = th.get_member(m)
    assert member["outstanding_fees_cents"] == 0
    assert member["waived_fees_cents"] == 30000
    th.assert_fee_ledger_conserved(member, 30000)


# --------------------------------------------------------------------------- #
# optimistic_concurrency (queue B)
# --------------------------------------------------------------------------- #
def test_stale_member_version_on_second_issue_rejected(api, admin):
    """PRD §2.7: "two strictly sequential issue requests carrying the same observed
    member version cannot both succeed, since the second's version is stale."
    PRD §2.7: "If `expected_member_version` does not equal the member's current
    `version` at issue time, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_member_version_on_dues_invoice
    """
    th.make_tier("SAIL")
    dock = th.make_dock()["id"]
    m = th.make_member("SAIL", dock)["id"]
    mv = th.get_member_version(m)
    th.issue_dues_invoice(m, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", mv)  # bumps version
    resp = api.create_dues_invoice(
        m, th.create_dues_invoice_payload("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", mv), admin
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_correct_member_version_succeeds_and_increments(api, admin):
    """PRD §2.7: "Because a successful issuance legitimately supersedes any prior unpaid
    invoice for that member and increments the member's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_member_version_succeeds_and_increments
    """
    th.make_tier("SAIL")
    dock = th.make_dock()["id"]
    m = th.make_member("SAIL", dock)["id"]
    mv = th.get_member_version(m)
    resp = api.create_dues_invoice(
        m, th.create_dues_invoice_payload("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", mv), admin
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ISSUED"
    assert th.get_member_version(m) == mv + 1


# --------------------------------------------------------------------------- #
# endpoints (queue B)
# --------------------------------------------------------------------------- #
def test_pay_invoice_settles_rolled_fee(api):
    """PRD §3.8: "moves the invoice to `PAID`, and settles each rolled fee that was
    `ASSESSED` to `PAID`."

    Design: Corner/endpoints/pay_invoice_settles_rolled_fees
    """
    ctx = th.setup_active_basic_member("CRUISE")
    m, b1 = ctx["member_id"], ctx["boat_ids"][0]
    r = th.request_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.assessed_damage_fee(r["id"], b1, "MINOR", 10000)
    fee = th.find_fees(member_id=m, fee_type="DAMAGE")[0]
    th.set_clock("2026-05-01T01:00:00Z")  # advance clock so the fee's assessed_at is strictly before issue/payment
    mv = th.get_member_version(m)
    inv = th.issue_dues_invoice(m, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", mv)
    th.pay_dues_invoice(m, inv["id"])
    settled = th.get_dues_invoice(inv["id"])
    assert settled["status"] == "PAID"
    assert settled["final_total_cents"] == 25850  # 15000 + round_half_up(10000*1.085)=10850
    assert th.get_fee(fee["id"])["status"] == "PAID"


def test_list_reservations_pagination(api, admin):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults
    to 10, may not be smaller than 1, and may not exceed 100."
    PRD §2.3: "The `meta` object of any list response includes the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_reservations_pagination
    """
    ctx = th.setup_active_basic_member("SAIL", tier_overrides={"max_active_reservations": 3})
    m, dock = ctx["member_id"], ctx["dock_id"]
    th.request_reservation(m, dock, "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.request_reservation(m, dock, "PONTOON", "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
    th.request_reservation(m, dock, "PONTOON", "2026-05-07T10:00:00Z", "2026-05-07T12:00:00Z")
    resp = api.list_reservations(admin, params={"member_id": m, "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


# --------------------------------------------------------------------------- #
# consistency_model (queue B) — FK reverse-reachability
# --------------------------------------------------------------------------- #
def test_system_fee_reachable_by_member_filter(api):
    """PRD §2.4: "damage reports by `reservation_id` or `boat_id`; fees by `member_id`
    or `reservation_id`; and dues invoices by `member_id`."
    PRD §3.6: "A fuel fee is charged when `fuel_at_return` comes back below the
    25-percent fuel floor: the fee is 100 cents for every percentage point of the drop
    from `fuel_at_checkout` down to `fuel_at_return`".

    Design: Corner/consistency_model/fk_reverse_reachability_fees_by_member
    """
    ctx = th.setup_active_basic_member("SAIL")
    m = ctx["member_id"]
    r = th.create_confirmed_reservation(m, ctx["dock_id"], "PONTOON", "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
    th.set_clock("2026-05-05T10:00:00Z")
    th.checkout_reservation(m, r["id"], 90)
    th.set_clock("2026-05-05T12:00:00Z")
    th.return_reservation(m, r["id"], 10)  # 100 * (90-10) = 8000 FUEL fee
    fees = th.find_fees(member_id=m, fee_type="FUEL")
    assert len(fees) == 1
    fee = fees[0]
    assert fee["member_id"] == m
    assert fee["reservation_id"] == r["id"]
    assert fee["fee_type"] == "FUEL"
    assert fee["amount_cents"] == 8000
