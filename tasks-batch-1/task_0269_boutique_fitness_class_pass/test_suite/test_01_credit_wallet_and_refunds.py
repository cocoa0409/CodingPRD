"""Membership wallet funding, prorated cancellation refunds, rollover, and credit
conservation. Translates difficulty-design dual_variant_calc / combinatorial_formula
(refund) / boundary_precision_check (rollover) / compensating_invariant (credit)
plus the corner instances for expiry forfeiture and wallet immutability.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_network, setup_member_with_membership, create_member,
    create_active_membership, reserve, get_membership, get_session,
    set_clock, api_client, make_member_headers, TEST_USERS,
    assert_wallet_entry,
)

ADMIN = TEST_USERS["network_admin_headers"]


def test_cancel_membership_prorated_refund_for_membership_plan(api):
    """PRD §3.4: "The refund is then the plan's `price_cents` multiplied by the ratio
    of those remaining days to the full `validity_days` — the ratio kept at full
    precision, multiplied into the price, and rounded half up to a whole cent exactly
    once at the end (never round the ratio first)."

    Design: Difficulty/dual_variant_calc/refund_membership_prorated_vs_pack_no_refund
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly Unlimited", "price_cents": 8000, "grant_credits": 20,
        "validity_days": 30, "rollover_cap": 8, "freeze_max_days": 14,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One", active=True)
    set_clock("2026-06-10T00:00:00Z")  # 9 whole days elapsed, no freeze

    res = api.cancel_membership(membership["id"], make_member_headers(member["id"]))
    cancelled = validate_success(res, 200)
    # 8000 * (30 - 9) / 30 = 8000 * 0.7 = 5600
    assert cancelled["refund_cents"] == 5600, f"expected 5600, got {cancelled['refund_cents']}"
    assert cancelled["status"] == "CANCELLED"


def test_cancel_membership_no_refund_for_credit_pack(api):
    """PRD §3.4: "This proration applies in full only to `MEMBERSHIP`-kind plans; for
    `INTRO` and `CREDIT_PACK` plans the refund is always 0, because packs are
    non-refundable."

    Design: Difficulty/dual_variant_calc/refund_membership_prorated_vs_pack_no_refund
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="CREDIT_PACK", plan_overrides={
        "name": "20 Pack", "price_cents": 8000, "grant_credits": 20, "validity_days": 30,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], email="m2@x.com", full_name="M Two", active=True)
    set_clock("2026-06-10T00:00:00Z")

    res = api.cancel_membership(membership["id"], make_member_headers(member["id"]))
    cancelled = validate_success(res, 200)
    assert cancelled["refund_cents"] == 0, f"CREDIT_PACK must refund 0, got {cancelled['refund_cents']}"
    assert cancelled["status"] == "CANCELLED"


def test_refund_rounding_order_single_final_round(api):
    """PRD §2.8: "Where a monetary figure is derived by multiplication — notably the
    prorated cancellation refund of §3.4 — the multiplication is carried at full
    precision and the result is rounded half up to a whole cent exactly once, at the
    very end."

    Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned_single_final_round
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly", "price_cents": 10000, "grant_credits": 20,
        "validity_days": 30, "rollover_cap": 8, "freeze_max_days": 14,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One", active=True)
    set_clock("2026-06-11T00:00:00Z")  # exactly 10 whole days elapsed

    res = api.cancel_membership(membership["id"], make_member_headers(member["id"]))
    cancelled = validate_success(res, 200)
    # 10000 * (20/30) = 6666.67 -> round_half_up -> 6667 (NOT 0.67*10000 = 6700)
    assert cancelled["refund_cents"] == 6667, (
        f"expected single-final-round 6667, got {cancelled['refund_cents']}")
    assert cancelled["status"] == "CANCELLED"


def test_refund_full_price_when_no_days_elapsed(api):
    """PRD §3.4: "The remaining portion of the cycle is `validity_days` minus
    `elapsed_days`, floored at zero so it never goes negative. The refund is then the
    plan's `price_cents` multiplied by the ratio of those remaining days to the full
    `validity_days` — the ratio kept at full precision, multiplied into the price, and
    rounded half up to a whole cent exactly once at the end (never round the ratio
    first)."

    Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned_single_final_round
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly", "price_cents": 10000, "grant_credits": 20,
        "validity_days": 30, "rollover_cap": 8, "freeze_max_days": 14,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], email="m1@x.com", full_name="M One", active=True)
    # Cancel at the same instant as cycle_start: 0 elapsed days -> ratio 30/30 = 1.0.

    res = api.cancel_membership(membership["id"], make_member_headers(member["id"]))
    cancelled = validate_success(res, 200)
    # 10000 * (30/30) = 10000 exactly; the ratio is 1.0 so no rounding divergence.
    assert cancelled["refund_cents"] == 10000, (
        f"expected full price 10000 at 0 elapsed days, got {cancelled['refund_cents']}")
    assert cancelled["status"] == "CANCELLED"


def test_rollover_at_cap_boundary_rolls_all_no_forfeit(api):
    """PRD §3.3: "The number of credits carried forward, recorded in
    `rolled_over_credits`, is the smaller of the membership's `credit_balance` at the
    moment of renewal and the plan's `rollover_cap`."
    PRD §3.3: "After renewal the `credit_balance` equals `rolled_over_credits` plus the
    plan's `grant_credits`."

    Design: Difficulty/boundary_precision_check/rollover_at_cap_boundary_zero_vs_one_forfeit
    """
    set_clock("2026-06-01T00:00:00Z")
    studio = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly8", "price_cents": 8000, "grant_credits": 8,
        "validity_days": 30, "rollover_cap": 8, "freeze_max_days": 0,
    })
    member, membership = setup_member_with_membership(
        studio["studio"]["id"], studio["plan"]["id"], email="mc@x.com", full_name="M C", active=True)
    set_clock("2026-07-02T00:00:00Z")  # >= expires_at

    res = api.renew_membership(membership["id"], ADMIN)
    renewed = validate_success(res, 200)
    assert renewed["rolled_over_credits"] == 8, f"expected 8 rolled, got {renewed['rolled_over_credits']}"
    assert renewed["credit_balance"] == 16, f"expected 8 rolled + 8 granted = 16, got {renewed['credit_balance']}"


def test_rollover_one_above_cap_forfeits_single_credit(api):
    """PRD §3.3: "Any surplus — the `credit_balance` minus `rolled_over_credits` — is
    forfeited; when that forfeited amount is greater than zero, a ledger line of `kind`
    `ROLLOVER_FORFEIT` is appended carrying a negative `delta` equal to the forfeited
    amount."
    PRD §3.3: "whereas a balance one credit above the cap rolls the cap and forfeits
    that single surplus credit."

    Design: Difficulty/boundary_precision_check/rollover_at_cap_boundary_zero_vs_one_forfeit
    """
    set_clock("2026-06-01T00:00:00Z")
    studio = setup_network(plan_kind="MEMBERSHIP", plan_overrides={
        "name": "Monthly9", "price_cents": 9000, "grant_credits": 9,
        "validity_days": 30, "rollover_cap": 8, "freeze_max_days": 0,
    })
    member, membership = setup_member_with_membership(
        studio["studio"]["id"], studio["plan"]["id"], email="md@x.com", full_name="M D", active=True)
    set_clock("2026-07-02T00:00:00Z")  # >= expires_at; balance is 9 (== grant)

    res = api.renew_membership(membership["id"], ADMIN)
    renewed = validate_success(res, 200)
    assert renewed["rolled_over_credits"] == 8, f"expected 8 rolled, got {renewed['rolled_over_credits']}"
    assert renewed["credit_balance"] == 17, f"expected 8 rolled + 9 granted = 17, got {renewed['credit_balance']}"
    # exactly one credit forfeited via a ROLLOVER_FORFEIT delta of -1
    entries, _ = get_success_data(
        api.list_membership_wallet_entries(membership["id"], make_member_headers(member["id"]))
    ), None
    rows = entries if isinstance(entries, list) else entries.get("data", entries)
    forfeits = [e for e in rows if e["kind"] == "ROLLOVER_FORFEIT"]
    assert any(e["delta"] == -1 for e in forfeits), f"expected a ROLLOVER_FORFEIT delta -1, got {forfeits}"


def test_credit_conservation_book_then_early_cancel(api):
    """PRD §3.7: "Cancelling a `BOOKED` reservation **outside** the late-cancel window —
    when the current clock is strictly before `starts_at` minus `late_cancel_window_hours`
    hours — is an early cancel: `booking_status` becomes `RELEASED`, `attendance_status`
    becomes `CANCELLED`, the `credits_charged` are refunded through a `CANCEL_REFUND`
    wallet line carrying a positive `delta`, `booked_count` is decremented, and the freed
    seat triggers the auto-promotion path below. No fee is charged."

    Design: Difficulty/compensating_invariant/credit_conservation_book_then_early_cancel
    """
    set_clock("2026-06-25T00:00:00Z")  # well outside the 12h window of a 07-01 10:00 session
    net = setup_network(plan_overrides={
        "name": "20 Pack", "price_cents": 8000, "grant_credits": 20, "validity_days": 60,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], active=True)
    r1 = reserve(_published(api, net, "2026-07-01T10:00:00Z", seat_capacity=5)["id"],
                 member["id"], membership["id"])

    res = api.cancel_reservation(r1["id"], make_member_headers(member["id"]))
    cancelled = validate_success(res, 200)
    assert cancelled["attendance_status"] == "CANCELLED"
    assert cancelled["late_fee_cents"] == 0

    sub = get_membership(membership["id"], member["id"])
    assert sub["credit_balance"] == 20, f"debit -5 then refund +5 must net to 20, got {sub['credit_balance']}"
    # No FeeCharge exists for an early cancel.
    fees = get_success_data(api.list_fees(ADMIN, params={"reservation_id": r1["id"]}))
    rows = fees if isinstance(fees, list) else fees.get("data", fees)
    assert rows == [] or len(rows) == 0, f"early cancel must assess no fee, got {rows}"


def test_credit_conservation_wallet_ledger_delta_sum(api):
    """PRD §2.5: "A membership's `credit_balance` is the running sum of the `delta`
    values of all `WalletEntry` rows attached to it."
    PRD §3.7: "the `credits_charged` are refunded through a `CANCEL_REFUND` wallet line
    carrying a positive `delta`".

    Design: Difficulty/compensating_invariant/credit_conservation_book_then_early_cancel
    """
    set_clock("2026-06-25T00:00:00Z")
    net = setup_network(plan_overrides={
        "name": "20 Pack", "price_cents": 8000, "grant_credits": 20, "validity_days": 60,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], active=True)
    r1 = reserve(_published(api, net, "2026-07-01T10:00:00Z", seat_capacity=5)["id"],
                 member["id"], membership["id"])
    validate_success(api.cancel_reservation(r1["id"], make_member_headers(member["id"])), 200)

    entries = get_success_data(
        api.list_membership_wallet_entries(membership["id"], make_member_headers(member["id"])))
    rows = entries if isinstance(entries, list) else entries.get("data", entries)
    # GRANT(+20), RESERVE_DEBIT(-5), CANCEL_REFUND(+5) -> running sum == 20.
    assert sum(e["delta"] for e in rows) == 20, (
        f"wallet delta sum must equal the conserved balance 20, got {[e['delta'] for e in rows]}")
    assert any(e["kind"] == "RESERVE_DEBIT" and e["delta"] == -5 for e in rows)
    assert any(e["kind"] == "CANCEL_REFUND" and e["delta"] == 5 for e in rows)


def test_expiry_forfeits_intro_credits_and_zeroes_balance(api):
    """PRD §3.4: "A membership in `ACTIVE` whose plan `kind` is not `MEMBERSHIP` — that
    is, an `INTRO` or `CREDIT_PACK` membership that does not auto-renew — and whose
    current clock has reached or passed `expires_at` transitions `ACTIVE → EXPIRED`."
    PRD §3.4: "the entire remaining `credit_balance` is forfeited through an
    `EXPIRY_FORFEIT` ledger line carrying a negative `delta` when the balance is greater
    than zero, and `credit_balance` is recomputed to 0."

    Design: Corner/state_machines/expiry_ops_forfeits_intro_credits
    """
    set_clock("2026-06-01T00:00:00Z")
    net = setup_network(plan_kind="CREDIT_PACK", plan_overrides={
        "name": "20 Pack", "price_cents": 8000, "grant_credits": 20, "validity_days": 30,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], active=True)
    set_clock("2026-07-02T00:00:00Z")

    validate_success(api.run_expiry(ADMIN), 200)
    sub = get_membership(membership["id"], member["id"])
    assert sub["status"] == "EXPIRED"
    assert sub["credit_balance"] == 0
    entries = get_success_data(
        api.list_membership_wallet_entries(membership["id"], make_member_headers(member["id"])))
    rows = entries if isinstance(entries, list) else entries.get("data", entries)
    assert any(e["kind"] == "EXPIRY_FORFEIT" and e["delta"] == -20 for e in rows), (
        f"expected EXPIRY_FORFEIT delta -20, got {rows}")


def test_wallet_entry_is_immutable_grant_with_no_version(api):
    """PRD §2.4: "A `WalletEntry` is an immutable ledger record: it carries only `id`
    and `created_at`. It has no `updated_at` and no `version`, because a ledger line,
    once written, is never edited — corrections are expressed by appending new entries,
    not by rewriting old ones."
    PRD §3.2: "A grant ledger line is appended (a `WalletEntry` of `kind` `GRANT`
    carrying a positive `delta` equal to the plan's `grant_credits` and bearing the
    `membership_id`), and `credit_balance` is recomputed."

    Design: Corner/entities/walletentry_immutable_no_version_field
    """
    net = setup_network(plan_kind="CREDIT_PACK", plan_overrides={
        "name": "20 Pack", "price_cents": 8000, "grant_credits": 20, "validity_days": 60,
    })
    member, membership = setup_member_with_membership(
        net["studio"]["id"], net["plan"]["id"], active=True)

    entries = get_success_data(
        api.list_membership_wallet_entries(membership["id"], make_member_headers(member["id"])))
    rows = entries if isinstance(entries, list) else entries.get("data", entries)
    grants = [e for e in rows if e["kind"] == "GRANT"]
    assert len(grants) == 1, f"expected exactly one GRANT entry, got {rows}"
    assert grants[0]["delta"] == 20
    for e in rows:
        assert_wallet_entry(e)


# ── helper used by credit-conservation test ────────────────────────────────
def _published(api, net, starts_at, seat_capacity):
    from test_helpers import create_published_session
    return create_published_session(
        net["studio"]["id"], net["room"]["id"], net["instructor"]["id"],
        net["template"]["id"], starts_at=starts_at, seat_capacity=seat_capacity)
