"""Money cascade & conservation: completion -> payout -> settlement charge -> retailer balance;
redo hold; cancel-after-complete reversal; decline slot release; settlement run; rating average."""
from test_helpers import (
    validate_success, PayoutStatus, SettlementEntryStatus, SettlementEntryType,
    WorkOrderStatus, AssignmentStatus, TEST_USERS,
    setup_completed_order, setup_dispatched_order, request_redo, cancel_order_admin,
    decline_assignment, payout_for, settlement_entries_for, make_customer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _simple_completed(api):
    """Base 12000, commission 1000bps, no add-ons/parts, standard hours -> final 12000,
    payout 9000, CHARGE 10800."""
    return setup_completed_order(
        api, base_price_cents=12000, commission_rate_bps=1000,
        scheduled_start="2026-03-05T09:00:00Z", scheduled_end="2026-03-05T10:00:00Z",
        clock="2026-03-05T10:00:00Z")


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/complete_cascades_payout_then_settlement_entry_then_retailer_balance
# ---------------------------------------------------------------------------
def test_complete_creates_payout_charge_and_retailer_balance(api):
    """PRD §3.7: "Creation of that payout cascades into a `RetailerSettlementEntry` of `entry_type`
    `CHARGE` in status `PENDING`, linking the `retailer_id`, the `work_order_id`, and the
    triggering `payout_record_id`. Its `amount_cents` is what the retailer owes the platform: the
    order's `final_price_cents` minus the retailer's retained referral fee, where the referral fee
    (`referral_fee_cents`) is the retailer's `commission_rate_bps` applied to the install task's
    `base_price_cents` — that is, `base_price_cents` times `commission_rate_bps` divided by 10000,
    rounded half up to a whole cent."
    PRD §3.7: "A retailer's `settlement_balance_cents` is the sum of `amount_cents` over that
    retailer's settlement entries whose `status` is `PENDING`"

    Design: Difficulty/transitive_cascade/complete_cascades_payout_then_settlement_entry_then_retailer_balance
    """
    ctx = _simple_completed(api)
    assert ctx["payout"]["status"] == PayoutStatus.PENDING.value
    assert ctx["payout"]["payout_cents"] == 9000
    entry = ctx["settlement_entries"][0]
    assert entry["entry_type"] == SettlementEntryType.CHARGE.value
    assert entry["status"] == SettlementEntryStatus.PENDING.value
    assert entry["amount_cents"] == 10800, f"expected 10800, got {entry['amount_cents']}"
    retailer = validate_success(api.get_retailer(ctx["retailer"]["id"], ADMIN), 200)
    assert retailer["settlement_balance_cents"] == 10800


def test_complete_creates_exactly_one_payout_and_one_charge(api):
    """PRD §3.7: "The system creates a `PayoutRecord` in status `PENDING` linked to the completed
    order's `work_order_id`, the appointment `pro_id`, and the referring `retailer_id`"

    Design: Difficulty/transitive_cascade/complete_cascades_payout_then_settlement_entry_then_retailer_balance
    """
    ctx = _simple_completed(api)
    wo_id = ctx["wo"]["id"]
    payouts = api.list_payouts(ADMIN, params={"work_order_id": wo_id}).json()["data"]
    entries = settlement_entries_for(api, wo_id)
    assert len(payouts) == 1, f"expected exactly one payout, got {len(payouts)}"
    assert len(entries) == 1, f"expected exactly one settlement entry, got {len(entries)}"
    assert entries[0]["entry_type"] == SettlementEntryType.CHARGE.value


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/request_redo_cascades_payout_hold_then_pending_payout_recompute
# ---------------------------------------------------------------------------
def test_request_redo_holds_payout(api):
    """PRD §3.8: "A redo request advances the order from `COMPLETED` to `REDO_REQUESTED`,
    increments the order's `redo_count` by 1, moves the order's payout from `PENDING` to `HELD`,
    and recomputes the pro's `pending_payout_cents` (which now excludes the held payout)."

    Design: Difficulty/transitive_cascade/request_redo_cascades_payout_hold_then_pending_payout_recompute
    """
    ctx = _simple_completed(api)
    request_redo(api, ctx["wo"]["id"], ctx["customer"]["id"])
    payout = payout_for(api, ctx["wo"]["id"])
    assert payout["status"] == PayoutStatus.HELD.value
    pro = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro["pending_payout_cents"] == 0, f"HELD excluded, got {pro['pending_payout_cents']}"


def test_pending_payout_excludes_held_but_included_pending(api):
    """PRD §3.7: "A pro's `pending_payout_cents` is the sum of `payout_cents` over that pro's payout
    records whose `status` is either `PENDING` or `RELEASED`; `HELD` and `REVERSED` payouts are
    excluded."

    Design: Difficulty/transitive_cascade/request_redo_cascades_payout_hold_then_pending_payout_recompute
    """
    ctx = _simple_completed(api)
    pro_before = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro_before["pending_payout_cents"] == 9000, "PENDING payout counts before redo"
    request_redo(api, ctx["wo"]["id"], ctx["customer"]["id"])
    pro_after = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro_after["pending_payout_cents"] == 0, "HELD payout excluded after redo"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/cancel_after_complete_conserves_retailer_settlement_balance
# ---------------------------------------------------------------------------
def test_cancel_after_complete_conserves_retailer_balance(api):
    """PRD §3.8: "In either path the retailer's `settlement_balance_cents` and the appointment
    pro's `pending_payout_cents` are recomputed, leaving this order's net contribution to both at 0."

    Design: Difficulty/compensating_invariant/cancel_after_complete_conserves_retailer_settlement_balance
    """
    ctx = _simple_completed(api)
    wo = cancel_order_admin(api, ctx["wo"]["id"], reason="customer no longer needs install")
    assert wo["status"] == WorkOrderStatus.CANCELLED.value
    retailer = validate_success(api.get_retailer(ctx["retailer"]["id"], ADMIN), 200)
    assert retailer["settlement_balance_cents"] == 0
    pro = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro["pending_payout_cents"] == 0


def test_cancel_after_complete_reverses_payout_and_charge(api):
    """PRD §3.8: "the order's payout, whether `PENDING` or `HELD`, is reversed to `REVERSED`; and
    the retailer settlement charge is unwound — if the order's `CHARGE` settlement entry is still
    `PENDING`, it is moved to `REVERSED` so it stops contributing to the balance"

    Design: Difficulty/compensating_invariant/cancel_after_complete_conserves_retailer_settlement_balance
    """
    ctx = _simple_completed(api)
    cancel_order_admin(api, ctx["wo"]["id"])
    payout = payout_for(api, ctx["wo"]["id"])
    assert payout["status"] == PayoutStatus.REVERSED.value
    entry = settlement_entries_for(api, ctx["wo"]["id"])[0]
    assert entry["status"] == SettlementEntryStatus.REVERSED.value


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/offer_then_decline_conserves_pro_reserved_slot_count
# ---------------------------------------------------------------------------
def test_decline_releases_reserved_slot_and_reverts_order(api):
    """PRD §3.5: "an `OFFERED` assignment moves it to `DECLINED`, stamps `responded_at`, decrements
    the pro's `reserved_slot_count` by 1, and reverts the parent work order from `DISPATCHED` back
    to `SCHEDULED` with its `appointment_pro_id` cleared"

    Design: Difficulty/compensating_invariant/offer_then_decline_conserves_pro_reserved_slot_count
    """
    ctx = setup_dispatched_order(api)
    asg = decline_assignment(api, ctx["assignment"]["id"], ctx["pro"]["id"])
    assert asg["status"] == AssignmentStatus.DECLINED.value
    pro = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro["reserved_slot_count"] == 0
    wo = validate_success(api.get_work_order(ctx["wo"]["id"], ADMIN), 200)
    assert wo["status"] == WorkOrderStatus.SCHEDULED.value
    assert wo["appointment_pro_id"] is None


def test_dispatch_reserves_slot_then_decline_conserves_to_zero(api):
    """PRD §3.4: "increments the selected pro's `reserved_slot_count` by 1"
    PRD §3.5: "the count reflects how many of the pro's assignments are currently in `OFFERED` or
    `ACCEPTED`."

    Design: Difficulty/compensating_invariant/offer_then_decline_conserves_pro_reserved_slot_count
    """
    ctx = setup_dispatched_order(api)
    pro_reserved = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro_reserved["reserved_slot_count"] == 1, "one OFFERED assignment reserves a slot"
    decline_assignment(api, ctx["assignment"]["id"], ctx["pro"]["id"])
    pro_after = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro_after["reserved_slot_count"] == 0, "decline returns the count to its pre-offer value"


# ---------------------------------------------------------------------------
# Corner/calculations/settlement_run_settles_pending_charge_and_returns_summary
# ---------------------------------------------------------------------------
def test_settlement_run_settles_pending_charge_and_returns_summary(api):
    """PRD §3.7: "The run selects that retailer's settlement entries whose `status` is `PENDING` and
    whose `created_at` is at or before `period_end` (inclusive), moves each to `SETTLED`, and stamps
    each `settled_at` with the current clock. It returns an inline summary object containing the
    `retailer_id`, the `settled_entry_count` (how many entries were settled), the
    `gross_settled_cents` (the sum of `amount_cents` over the settled entries, where REVERSAL rows
    contribute negative amounts), and the `remaining_balance_cents` (the retailer's
    `settlement_balance_cents` after the run"

    Design: Corner/calculations/settlement_run_settles_pending_charge_and_returns_summary
    """
    ctx = _simple_completed(api)
    summary = validate_success(
        api.run_settlement(ctx["retailer"]["id"], {"period_end": "2026-04-01T00:00:00Z"}, ADMIN), 200)
    assert summary["settled_entry_count"] == 1
    assert summary["gross_settled_cents"] == 10800
    assert summary["remaining_balance_cents"] == 0
    retailer = validate_success(api.get_retailer(ctx["retailer"]["id"], ADMIN), 200)
    assert retailer["settlement_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/calculations/pro_rating_average_after_one_rating
# ---------------------------------------------------------------------------
def test_pro_rating_average_after_one_rating(api):
    """PRD §3.9: "Each new rating updates the rated pro's running aggregates: `rating_sum`
    accumulates by adding the new `stars`, `rating_count` increases by 1, and `rating_avg` is
    recomputed as `rating_sum` divided by `rating_count`, rounded half up to two decimal places
    (and defined as 0 when `rating_count` is 0)."

    Design: Corner/calculations/pro_rating_average_after_one_rating
    """
    ctx = _simple_completed(api)
    validate_success(
        api.create_rating(ctx["wo"]["id"], {"stars": 5}, make_customer_headers(ctx["customer"]["id"])), 201)
    pro = validate_success(api.get_pro(ctx["pro"]["id"], ADMIN), 200)
    assert pro["rating_count"] == 1
    assert pro["rating_sum"] == 5
    assert pro["rating_avg"] == 5.0
