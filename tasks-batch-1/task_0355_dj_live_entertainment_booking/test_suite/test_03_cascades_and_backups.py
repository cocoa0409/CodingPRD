"""Cancellation refund cascades, store-credit conservation, and backup promotion
swaps.

Covers Difficulty rules transitive_cascade and compensating_invariant, plus the
corner cancel-cascade instance. PRD §3.9 (cancel/refund) and §3.11 (promotion).
"""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, fixtures as fx

AGENT = fx.AGENT
ADMIN = fx.ADMIN


# =====================================================================
# Difficulty/transitive_cascade
# =====================================================================
def test_cancel_refund_routes_store_credit_to_client(api):
    """PRD §3.9: "For each captured payment, the refundable portion is the booking's
    `amount_paid_cents` reduced by the `cancellation_fee_cents`, and that refund is
    routed according to the payment's `refund_destination`: a routed refund moves the
    payment's `settlement_status` to `REFUNDED`, and when the destination is
    `STORE_CREDIT` the refundable portion is added to the owning client's
    `store_credit_cents` balance."

    Design: Difficulty/transitive_cascade/cancel_cascade_depth3_payment_to_client_credit
    """
    cat = fx.setup_charged_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(
        cat, deposit_cents=81000, refund_destination="STORE_CREDIT",
        event_zone_id=cat["zevent_id"], miles=20,
        event_start_utc="2026-08-01T20:00:00Z",
    )
    cancelled = validate_success(api.cancel_booking(confirmed["id"], AGENT))
    assert cancelled["cancellation_fee_cents"] == 64800, cancelled["cancellation_fee_cents"]

    pay_now = validate_success(api.get_payment(dep["id"], AGENT))
    assert pay_now["settlement_status"] == "REFUNDED", pay_now["settlement_status"]

    client_now = validate_success(api.get_client(cat["cli_id"], AGENT))
    assert client_now["store_credit_cents"] == 16200, client_now["store_credit_cents"]


def test_cancel_refund_to_original_does_not_add_store_credit(api):
    """PRD §3.9: "that refund is routed according to the payment's `refund_destination`:
    a routed refund moves the payment's `settlement_status` to `REFUNDED`, and when the
    destination is `STORE_CREDIT` the refundable portion is added to the owning client's
    `store_credit_cents` balance."

    Design: Difficulty/transitive_cascade/cancel_cascade_depth3_payment_to_client_credit
    """
    cat = fx.setup_home_catalogue()
    # ORIGINAL destination (the factory default): refund does not route to store credit.
    cat2, held = fx.create_held_booking(cat, contracted_set_minutes=120)
    dep = fx.create_payment(held["id"], kind="DEPOSIT", amount_cents=62500)
    fx.capture_payment(dep["id"])
    fx.set_clock("2026-06-14T00:00:00Z")

    cancelled = validate_success(api.cancel_booking(held["id"], AGENT))
    pay_now = validate_success(api.get_payment(dep["id"], AGENT))
    client_now = validate_success(api.get_client(cat["cli_id"], AGENT))

    assert pay_now["settlement_status"] == "REFUNDED", pay_now["settlement_status"]
    assert client_now["store_credit_cents"] == 0, client_now["store_credit_cents"]


def test_promote_backup_swaps_active_performer_and_availability(api):
    """PRD §3.11: "A successful promotion moves the targeted assignment to `PROMOTED`,
    reassigns the booking's `active_performer_id` to the candidate, returns the former
    active performer's `availability_status` to `AVAILABLE` while decrementing that
    performer's `reliability_score` by 10 (floored at 0), moves the new performer's
    `availability_status` to `BOOKED`, and expires every other `OFFERED` or `ACCEPTED`
    backup assignment on the booking by moving it to `EXPIRED`."

    Design: Difficulty/transitive_cascade/promote_backup_cascade_depth2_performer_swap
    """
    s = fx.setup_confirmed_with_accepted_backup()
    booking = s["booking"]
    validate_success(api.promote_backup(booking["id"], s["backup_assignment"]["id"],
                                        s["version_pre_promote"], AGENT))

    bk_now = validate_success(api.get_booking(booking["id"], AGENT))
    assert bk_now["active_performer_id"] == s["backup_id"], bk_now["active_performer_id"]

    primary = validate_success(api.get_performer(s["primary_id"], AGENT))
    assert primary["availability_status"] == "AVAILABLE", primary["availability_status"]

    backup = validate_success(api.get_performer(s["backup_id"], AGENT))
    assert backup["availability_status"] == "BOOKED", backup["availability_status"]


def test_promote_backup_expires_peer_backups(api):
    """PRD §3.11: "and expires every other `OFFERED` or `ACCEPTED` backup assignment
    on the booking by moving it to `EXPIRED`."

    Design: Difficulty/transitive_cascade/promote_backup_cascade_depth2_performer_swap
    """
    s = fx.setup_confirmed_with_two_accepted_backups()
    booking = s["booking"]
    # promote the lowest-rank (b1, ba1); ba2 must expire.
    promoted = validate_success(
        api.promote_backup(booking["id"], s["ba1"]["id"], s["version_pre_promote"], AGENT)
    )
    assert promoted["active_performer_id"] == s["b1_id"], promoted["active_performer_id"]

    ba2_now = validate_success(api.get_backup_assignment(s["ba2"]["id"], AGENT))
    assert ba2_now["status"] == "EXPIRED", ba2_now["status"]


# =====================================================================
# Difficulty/compensating_invariant
# =====================================================================
def test_cancel_conserves_money_fee_plus_credit_equals_captured(api):
    """PRD §3.9: "The resulting cancellation fee in cents is the quote total multiplied
    by the applicable fraction in basis points, divided by 10000, and rounded half up
    to whole cents; it is stored as `cancellation_fee_cents`."
    PRD §3.9: "For each captured payment, the refundable portion is the booking's
    `amount_paid_cents` reduced by the `cancellation_fee_cents`, and that refund is
    routed according to the payment's `refund_destination`: a routed refund moves the
    payment's `settlement_status` to `REFUNDED`, and when the destination is
    `STORE_CREDIT` the refundable portion is added to the owning client's
    `store_credit_cents` balance."

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_money_quote_equals_fee_plus_refund
    """
    cat = fx.setup_charged_catalogue()
    cat2, confirmed, ct_id, dep = fx.create_confirmed_booking(
        cat, deposit_cents=81000, refund_destination="STORE_CREDIT",
        event_zone_id=cat["zevent_id"], miles=20,
        event_start_utc="2026-08-01T20:00:00Z",
    )
    cancelled = validate_success(api.cancel_booking(confirmed["id"], AGENT))
    client_now = validate_success(api.get_client(cat["cli_id"], AGENT))

    assert cancelled["cancellation_fee_cents"] == 64800
    assert client_now["store_credit_cents"] == 16200
    assert cancelled["cancellation_fee_cents"] + client_now["store_credit_cents"] == 81000


def test_promote_conserves_single_booked_active_performer(api):
    """PRD §3.11: "A successful promotion moves the targeted assignment to `PROMOTED`,
    reassigns the booking's `active_performer_id` to the candidate, returns the former
    active performer's `availability_status` to `AVAILABLE` while decrementing that
    performer's `reliability_score` by 10 (floored at 0), moves the new performer's
    `availability_status` to `BOOKED`, and expires every other `OFFERED` or `ACCEPTED`
    backup assignment on the booking by moving it to `EXPIRED`."

    Design: Difficulty/compensating_invariant/promote_backup_conserves_performer_assignment_count
    """
    s = fx.setup_confirmed_with_accepted_backup()
    booking = s["booking"]
    validate_success(api.promote_backup(booking["id"], s["backup_assignment"]["id"],
                                        s["version_pre_promote"], AGENT))

    primary = validate_success(api.get_performer(s["primary_id"], AGENT))
    backup = validate_success(api.get_performer(s["backup_id"], AGENT))
    bk_now = validate_success(api.get_booking(booking["id"], AGENT))

    assert primary["availability_status"] == "AVAILABLE"
    assert backup["availability_status"] == "BOOKED"
    assert bk_now["active_performer_id"] == s["backup_id"]


def test_cancel_money_conserved_on_hold_store_credit(api):
    """PRD §3.9: "when it is at least 14 days but fewer than 30, the fee is 25%"
    PRD §3.9: "For each captured payment, the refundable portion is the booking's
    `amount_paid_cents` reduced by the `cancellation_fee_cents`, and that refund is
    routed according to the payment's `refund_destination`: a routed refund moves the
    payment's `settlement_status` to `REFUNDED`, and when the destination is
    `STORE_CREDIT` the refundable portion is added to the owning client's
    `store_credit_cents` balance."

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_money_quote_equals_fee_plus_refund
    """
    fx.set_clock("2026-07-12T00:00:00Z")  # lead 20 days -> 25% tier on HOLD
    zhome = fx.create_home_zone()
    pkg = fx.create_package()
    perf = fx.create_performer(zhome["id"])
    cli = fx.create_client()
    cat = {"zhome_id": zhome["id"], "pkg_id": pkg["id"], "perf_id": perf["id"],
           "cli_id": cli["id"]}
    bk = fx.create_booking(cat, event_zone_id=zhome["id"],
                           event_start_utc="2026-08-01T20:00:00Z", contracted_set_minutes=120)
    fx.hold_booking(bk["id"])
    dep = fx.create_payment(bk["id"], kind="DEPOSIT", amount_cents=62500,
                            refund_destination="STORE_CREDIT")
    fx.capture_payment(dep["id"])

    cancelled = validate_success(api.cancel_booking(bk["id"], AGENT))
    client_now = validate_success(api.get_client(cli["id"], AGENT))
    # quote 250000, 25% fee = 62500; refundable = 62500 - 62500 = 0 to credit.
    assert cancelled["cancellation_fee_cents"] == 62500, cancelled["cancellation_fee_cents"]
    assert client_now["store_credit_cents"] == 0, client_now["store_credit_cents"]
    assert cancelled["cancellation_fee_cents"] + client_now["store_credit_cents"] == 62500


def test_promote_leaves_exactly_one_booked_performer(api):
    """PRD §3.11: "returns the former active performer's `availability_status` to
    `AVAILABLE` while decrementing that performer's `reliability_score` by 10 (floored
    at 0), moves the new performer's `availability_status` to `BOOKED`"

    Design: Difficulty/compensating_invariant/promote_backup_conserves_performer_assignment_count
    """
    s = fx.setup_confirmed_with_two_accepted_backups()
    booking = s["booking"]
    validate_success(
        api.promote_backup(booking["id"], s["ba1"]["id"], s["version_pre_promote"], AGENT)
    )
    statuses = {
        s["primary_id"]: validate_success(api.get_performer(s["primary_id"], AGENT))["availability_status"],
        s["b1_id"]: validate_success(api.get_performer(s["b1_id"], AGENT))["availability_status"],
        s["b2_id"]: validate_success(api.get_performer(s["b2_id"], AGENT))["availability_status"],
    }
    booked = [pid for pid, st in statuses.items() if st == "BOOKED"]
    assert booked == [s["b1_id"]], (booked, statuses)
    assert statuses[s["primary_id"]] == "AVAILABLE"


# =====================================================================
# Corner/cross_cutting_complexity_layers (cascading_side_effects)
# =====================================================================
def test_cancel_reverts_performer_and_declines_contract(api):
    """PRD §3.9: "The cancellation also unwinds related records: any still-`ISSUED` or
    `SIGNED` contract on the booking moves to `DECLINED`, any backup assignment still
    in `OFFERED` or `ACCEPTED` moves to `EXPIRED`, and the current active performer's
    `availability_status` returns to `AVAILABLE`. The booking itself moves to its
    terminal `CANCELLED` state."

    Design: Corner/cross_cutting_complexity_layers/cancel_cascade_reverts_performer_and_contract
    """
    cat, bk, ct_id = fx.create_contract_sent_booking(contracted_set_minutes=120)
    cancelled = validate_success(api.cancel_booking(bk["id"], AGENT))
    assert cancelled["status"] == "CANCELLED"

    perf = validate_success(api.get_performer(cat["perf_id"], AGENT))
    assert perf["availability_status"] == "AVAILABLE", perf["availability_status"]

    contract = validate_success(api.get_contract(ct_id, AGENT))
    assert contract["status"] == "DECLINED", contract["status"]
