"""The money axis: the forward-looking authorization, the seven-step capture,
store-credit consumption and refunds."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_payment,
    build_catalog,
    canonical_world,
    grant_credit,
    make_member_headers,
    open_cycle,
    open_drop_run,
    place_order,
    record_receipt,
    refund_payload,
    salt_world,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["club_admin_headers"]
FINANCE = TEST_USERS["finance_headers"]


def _two_line_plus_order(api):
    """Mara (PLUS) with two whole-case lines of 5250 cents each, cycle locked."""
    w = build_catalog(api, items=("salt", "pepper"), include_ben=False)
    open_cycle(api, w)
    open_drop_run(api, w)
    placed = place_order(api, w, w.mara_id, w.drop_run_id, [("salt", 5), ("pepper", 5)])
    w.order_mara = placed["order"]["id"]
    w.lines["mara_salt"] = placed["lines"][0]["id"]
    w.lines["mara_pepper"] = placed["lines"][1]["id"]
    set_clock(api, "2026-05-25T00:00:00Z")
    validate_success(api.lock_cycle(w.cycle_id, ADMIN))
    return w


# ------------------------------------------------------- the two axes ------
def test_capture_moves_the_payment_axis_while_the_fulfilment_axis_stands_still(api):
    """PRD §3.8: "The payment axis of a member order runs independently of its
    fulfilment axis, and every movement on it mints a `Payment` record."
    PRD §3.8: "The order's `captured_cents` becomes `credit_applied_cents` plus
    `actual_total_cents`, the consumed grants are moved as described above, and the
    payment axis moves `AUTHORIZED → CAPTURED`."

    Design: Difficulty/non_linear_state_machine/member_order_fulfilment_and_payment_axes_advance_independently
    """
    w = canonical_world(api, "consolidated")

    before = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert before["status"] == "SHORT_FILLED"
    assert before["payment_status"] == "AUTHORIZED"
    assert before["authorized_amount_cents"] == 50720

    after = validate_success(api.capture_member_order(w.order_mara, {}, FINANCE))
    assert after["status"] == "SHORT_FILLED", "the fulfilment axis must not move"
    assert after["payment_status"] == "CAPTURED"
    assert after["captured_cents"] == 52218
    assert after["authorized_amount_cents"] == 50720


def test_receiving_moves_the_fulfilment_axis_while_the_payment_axis_stands_still(api):
    """PRD §3.6: "Correspondingly, a member order moves `LOCKED → FILLED` when
    every one of its lines has `allocated_units` equal to `confirmed_units`, and
    `LOCKED → SHORT_FILLED` when at least one line falls short; and an order can move
    `SHORT_FILLED → FILLED` when a later receipt raises every line to its full
    `confirmed_units`."
    PRD §3.3: "the order is created with status `DRAFT` on the fulfilment axis and
    `UNPAID` on the money axis, and both axes move independently thereafter."

    Design: Difficulty/non_linear_state_machine/member_order_fulfilment_and_payment_axes_advance_independently
    """
    w = canonical_world(api, "aggregates")

    before = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert before["status"] == "LOCKED"
    assert before["payment_status"] == "AUTHORIZED"

    record_receipt(api, w, "oat", 2)

    after = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert after["status"] == "SHORT_FILLED"
    assert after["payment_status"] == "AUTHORIZED", "the money axis must not move"
    assert after["captured_cents"] == 0


# ------------------------------------------- one rounding at order level ----
def test_order_discount_is_rounded_once_at_order_level_not_per_line(api):
    """PRD §3.8: "The estimated discount is that gross multiplied by the member's
    `discount_pct` and rounded half up to the whole cent. `estimated_total_cents` is
    the estimated gross less that discount, and `authorized_amount_cents` is
    `estimated_total_cents` multiplied by 1.10 — a ten-percent buffer — rounded half
    up to the whole cent."
    PRD §3.8: "There is exactly **one** rounding, applied to the order-level gross,
    not one rounding per line."

    Design: Difficulty/combinatorial_formula/order_discount_is_rounded_once_at_order_level_not_per_line
    """
    w = _two_line_plus_order(api)

    assert (
        validate_success(api.get_order_line(w.lines["mara_salt"], ADMIN))["unit_price_cents"]
        == 1050
    )
    salt = validate_success(api.get_order_line(w.lines["mara_salt"], ADMIN))
    assert salt["is_split_unit"] is False
    assert (
        validate_success(api.get_order_line(w.lines["mara_pepper"], ADMIN))["unit_price_cents"]
        == 1050
    )

    order = validate_success(
        api.authorize_member_order(
            w.order_mara, {"simulated_outcome": "SUCCEEDED"}, FINANCE
        )
    )
    assert order["estimated_total_cents"] == 9975
    assert order["authorized_amount_cents"] == 10973
    assert order["payment_status"] == "AUTHORIZED"


def test_a_failed_authorization_records_the_same_figure_and_the_retry_succeeds(api):
    """PRD §3.8: "On a `FAILED` outcome it creates a payment of kind
    `AUTHORIZATION` with status `FAILED` and `amount_cents` equal to the same
    computed figure, leaves the order's `authorized_amount_cents` at 0, and moves
    the axis `UNPAID → AUTH_FAILED`."
    PRD §3.8: "A retry after a failure is explicitly supported: a second successful
    attempt creates a second `AUTHORIZATION` payment with status `SUCCEEDED`, writes
    `authorized_amount_cents`, and moves the axis `AUTH_FAILED → AUTHORIZED`, which is
    what makes this axis cyclic rather than a one-way pipeline."

    Design: Difficulty/combinatorial_formula/order_discount_is_rounded_once_at_order_level_not_per_line
    """
    w = _two_line_plus_order(api)

    failed = validate_success(
        api.authorize_member_order(w.order_mara, {"simulated_outcome": "FAILED"}, FINANCE)
    )
    assert failed["payment_status"] == "AUTH_FAILED"
    assert failed["authorized_amount_cents"] == 0

    rows, _ = validate_paginated(
        api.list_payments(ADMIN, params={"member_order_id": w.order_mara})
    )
    assert len(rows) == 1
    assert_payment(rows[0])
    assert rows[0]["kind"] == "AUTHORIZATION"
    assert rows[0]["status"] == "FAILED"
    assert rows[0]["amount_cents"] == 10973

    retried = validate_success(
        api.authorize_member_order(
            w.order_mara, {"simulated_outcome": "SUCCEEDED"}, FINANCE
        )
    )
    assert retried["payment_status"] == "AUTHORIZED"
    assert retried["authorized_amount_cents"] == 10973

    rows, meta = validate_paginated(
        api.list_payments(
            ADMIN, params={"member_order_id": w.order_mara, "kind": "AUTHORIZATION"}
        )
    )
    assert meta["total_count"] == 2
    assert {(row["status"], row["amount_cents"]) for row in rows} == {
        ("FAILED", 10973),
        ("SUCCEEDED", 10973),
    }


# ------------------------------------------------------------ credit cap ----
def test_credit_cap_is_evaluated_after_discount_freight_and_surcharge(api):
    """PRD §3.8: "`pre_credit_total_cents` is `gross_cents` less
    `tier_discount_cents`, plus `freight_alloc_cents`, plus `reefer_alloc_cents`."
    PRD §3.8: "The credit cap is the floor of `pre_credit_total_cents` multiplied
    by 0.50 — store credit may never cover more than half an order."
    PRD §3.8: "`actual_total_cents` is `pre_credit_total_cents` less
    `credit_applied_cents`, and that is the amount the card capture attempts."

    Design: Difficulty/combinatorial_formula/credit_cap_is_evaluated_after_discount_freight_and_surcharge
    """
    w = canonical_world(api, "consolidated")
    grant = grant_credit(api, w, w.mara_id, 60000, "2026-12-01T00:00:00Z")

    order = validate_success(api.capture_member_order(w.order_mara, {}, FINANCE))
    assert order["gross_cents"] == 44840
    assert order["tier_discount_cents"] == 2242
    assert order["freight_alloc_cents"] == 3143
    assert order["reefer_alloc_cents"] == 6477
    assert order["pre_credit_total_cents"] == 52218
    assert order["credit_applied_cents"] == 26109
    assert order["actual_total_cents"] == 26109
    assert order["captured_cents"] == 52218

    stored = validate_success(api.get_credit_grant(grant["id"], ADMIN))
    assert stored["remaining_cents"] == 33891
    assert stored["status"] == "PARTIALLY_CONSUMED"


def test_credit_applied_is_limited_by_what_the_member_can_actually_produce(api):
    """PRD §3.8: "The amount wanted is `apply_credit_cents` when the capture
    request supplies it, and the credit cap otherwise. `credit_applied_cents` is the
    smallest of the amount wanted, the credit cap, and the credit the member can
    actually produce."
    PRD §3.8: "On success the capture creates up to two payment records: one of kind
    `CAPTURE` with method `STORE_CREDIT` and `amount_cents` equal to
    `credit_applied_cents` when that figure is above 0, written **first**, and one of
    kind `CAPTURE` with method `CARD` and `amount_cents` equal to
    `actual_total_cents` when that figure is above 0, written second."

    Design: Difficulty/combinatorial_formula/credit_cap_is_evaluated_after_discount_freight_and_surcharge
    """
    w = canonical_world(api, "consolidated")
    grant = grant_credit(api, w, w.mara_id, 1000, "2026-12-01T00:00:00Z")

    order = validate_success(api.capture_member_order(w.order_mara, {}, FINANCE))
    assert order["pre_credit_total_cents"] == 52218
    assert order["credit_applied_cents"] == 1000
    assert order["actual_total_cents"] == 51218
    assert order["captured_cents"] == 52218

    stored = validate_success(api.get_credit_grant(grant["id"], ADMIN))
    assert stored["remaining_cents"] == 0
    assert stored["status"] == "CONSUMED"

    rows, meta = validate_paginated(
        api.list_payments(
            ADMIN, params={"member_order_id": w.order_mara, "kind": "CAPTURE"}
        )
    )
    assert meta["total_count"] == 2
    assert rows[0]["method"] == "STORE_CREDIT"
    assert rows[0]["amount_cents"] == 1000
    assert rows[1]["method"] == "CARD"
    assert rows[1]["amount_cents"] == 51218


# ------------------------------------------------- soonest-expiry-first -----
def test_credit_fifo_drains_the_soonest_expiring_grant_first(api):
    """PRD §3.8: "They are ordered by ascending `expires_at` and then by ascending
    `created_at`, so the credit closest to being lost is spent first — draining by
    grant age instead would spend different grants and leave a different
    `remaining_cents` behind whenever an older grant expires later than a newer one."
    PRD §3.8: "Walking that order, each grant surrenders the smaller of its own
    `remaining_cents` and the amount still wanted; its `remaining_cents` falls by
    what it surrendered; it moves `ACTIVE → CONSUMED` or
    `PARTIALLY_CONSUMED → CONSUMED` when nothing is left, and
    `ACTIVE → PARTIALLY_CONSUMED` when something is; and the walk stops as soon as the
    wanted amount has been taken."

    Design: Difficulty/dual_variant_calc/credit_fifo_drains_the_soonest_expiring_grant_first
    """
    w = canonical_world(api, "consolidated")
    later = grant_credit(api, w, w.mara_id, 3000, "2026-08-01T00:00:00Z")
    sooner = grant_credit(api, w, w.mara_id, 5000, "2026-06-15T00:00:00Z")

    order = validate_success(
        api.capture_member_order(w.order_mara, {"apply_credit_cents": 4000}, FINANCE)
    )
    assert order["credit_applied_cents"] == 4000
    assert order["pre_credit_total_cents"] == 52218
    assert order["actual_total_cents"] == 48218
    assert order["captured_cents"] == 52218

    sooner_after = validate_success(api.get_credit_grant(sooner["id"], ADMIN))
    assert sooner_after["remaining_cents"] == 1000
    assert sooner_after["status"] == "PARTIALLY_CONSUMED"

    later_after = validate_success(api.get_credit_grant(later["id"], ADMIN))
    assert later_after["remaining_cents"] == 3000
    assert later_after["status"] == "ACTIVE"


def test_credit_fifo_moves_on_to_the_next_grant_once_the_first_is_exhausted(api):
    """PRD §3.8: "The credit the member can produce is drawn by a
    **soonest-expiry-first** rule, run immediately after the credit expiry sweep."
    PRD §3.8: "Walking that order, each grant surrenders the smaller of its own
    `remaining_cents` and the amount still wanted; its `remaining_cents` falls by
    what it surrendered; it moves `ACTIVE → CONSUMED` or
    `PARTIALLY_CONSUMED → CONSUMED` when nothing is left, and
    `ACTIVE → PARTIALLY_CONSUMED` when something is; and the walk stops as soon as the
    wanted amount has been taken."

    Design: Difficulty/dual_variant_calc/credit_fifo_drains_the_soonest_expiring_grant_first
    """
    w = canonical_world(api, "consolidated")
    later = grant_credit(api, w, w.mara_id, 3000, "2026-08-01T00:00:00Z")
    sooner = grant_credit(api, w, w.mara_id, 5000, "2026-06-15T00:00:00Z")

    order = validate_success(
        api.capture_member_order(w.order_mara, {"apply_credit_cents": 6000}, FINANCE)
    )
    assert order["credit_applied_cents"] == 6000
    assert order["actual_total_cents"] == 46218

    sooner_after = validate_success(api.get_credit_grant(sooner["id"], ADMIN))
    assert sooner_after["remaining_cents"] == 0
    assert sooner_after["status"] == "CONSUMED"

    later_after = validate_success(api.get_credit_grant(later["id"], ADMIN))
    assert later_after["remaining_cents"] == 2000
    assert later_after["status"] == "PARTIALLY_CONSUMED"


# ------------------------------------------- authorization reserves nothing --
def test_authorizing_then_cancelling_the_cycle_conserves_member_credit(api):
    """PRD §2.11: "**Member credit conserved on authorization void.** A member's
    `credit_balance_cents`, together with the sum of `remaining_cents` over that
    member's grants that have not expired, must be identical before an authorization
    and after that authorization is voided by cancelling the order. An authorization
    reserves nothing permanently."
    PRD §3.8: "Whenever the order moves to `CANCELLED` — by the member withdrawing a
    submitted order, or by the lock's hop 6, or by cycle cancellation — every
    successful `AUTHORIZATION` payment on it moves `SUCCEEDED → VOIDED`, the order's
    `payment_status` becomes `VOIDED`, and its `authorized_amount_cents` returns to 0,
    releasing anything the authorization had notionally held."

    Design: Difficulty/compensating_invariant/authorizing_then_cancelling_the_cycle_conserves_member_credit
    """
    w = salt_world(api)
    grant = grant_credit(api, w, w.mara_id, 5000, "2026-12-01T00:00:00Z")
    set_clock(api, "2026-05-25T00:00:00Z")
    validate_success(api.lock_cycle(w.cycle_id, ADMIN))
    validate_success(
        api.authorize_member_order(
            w.order_mara, {"simulated_outcome": "SUCCEEDED"}, FINANCE
        )
    )

    before_member = validate_success(api.get_member(w.mara_id, ADMIN))
    before_order = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert before_member["credit_balance_cents"] == 5000
    assert before_order["authorized_amount_cents"] == 5486
    assert before_order["payment_status"] == "AUTHORIZED"

    validate_success(api.cancel_cycle(w.cycle_id, ADMIN))

    after_member = validate_success(api.get_member(w.mara_id, ADMIN))
    assert after_member["credit_balance_cents"] == 5000

    after_grant = validate_success(api.get_credit_grant(grant["id"], ADMIN))
    assert after_grant["remaining_cents"] == 5000
    assert after_grant["status"] == "ACTIVE"

    after_order = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert after_order["authorized_amount_cents"] == 0
    assert after_order["captured_cents"] == 0
    assert after_order["payment_status"] == "VOIDED"
    assert after_order["status"] == "CANCELLED"


def test_the_voided_authorization_payment_is_the_only_money_record_left(api):
    """PRD §3.8: "Payments are minted directly into `SUCCEEDED` or `FAILED` by the
    operations below; the only transition a payment ever undergoes afterwards is
    `SUCCEEDED → VOIDED`, and only an `AUTHORIZATION` is eligible for it."
    PRD §2.11: "**Member credit conserved on authorization void.** A member's
    `credit_balance_cents`, together with the sum of `remaining_cents` over that
    member's grants that have not expired, must be identical before an authorization
    and after that authorization is voided by cancelling the order. An authorization
    reserves nothing permanently."

    Design: Difficulty/compensating_invariant/authorizing_then_cancelling_the_cycle_conserves_member_credit
    """
    w = salt_world(api)
    grant_credit(api, w, w.mara_id, 5000, "2026-12-01T00:00:00Z")
    set_clock(api, "2026-05-25T00:00:00Z")
    validate_success(api.lock_cycle(w.cycle_id, ADMIN))
    validate_success(
        api.authorize_member_order(
            w.order_mara, {"simulated_outcome": "SUCCEEDED"}, FINANCE
        )
    )
    validate_success(api.cancel_cycle(w.cycle_id, ADMIN))

    rows, meta = validate_paginated(
        api.list_payments(
            ADMIN,
            params={"member_order_id": w.order_mara, "kind": "AUTHORIZATION"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "VOIDED"
    assert rows[0]["amount_cents"] == 5486

    _, all_meta = validate_paginated(
        api.list_payments(ADMIN, params={"member_order_id": w.order_mara})
    )
    assert all_meta["total_count"] == 1

    grants, grant_meta = validate_paginated(
        api.list_credit_grants(ADMIN, params={"member_id": w.mara_id})
    )
    assert grant_meta["total_count"] == 1
    assert grants[0]["remaining_cents"] == 5000


# ------------------------------------------------------- fiscal refusals ----
def test_capture_variance_beyond_the_band_is_refused(api):
    """PRD §3.8: "The variance is `actual_total_cents` less
    `authorized_amount_cents`. The tolerance is the greater of 500 cents and
    `authorized_amount_cents` multiplied by 0.15 and rounded half up to the whole
    cent. The capture proceeds when the variance is less than or equal to the
    tolerance, and is refused with `ERR_PAYMENT_VARIANCE_EXCEEDED` otherwise."

    Design: Corner/calculations/capture_variance_beyond_the_band_is_refused
    """
    w = canonical_world(api, "consolidated", freight_cents=60000)

    validate_error(
        api.capture_member_order(w.order_mara, {}, FINANCE),
        ApiErrorId.ERR_PAYMENT_VARIANCE_EXCEEDED.value,
    )

    order = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert order["payment_status"] == "AUTHORIZED"
    assert order["captured_cents"] == 0
    assert order["freight_alloc_cents"] == 37717
    assert order["pre_credit_total_cents"] == 86792

    _, meta = validate_paginated(
        api.list_payments(
            ADMIN, params={"member_order_id": w.order_mara, "kind": "CAPTURE"}
        )
    )
    assert meta["total_count"] == 0


def test_applying_more_credit_than_the_cap_returns_credit_cap_exceeded(api):
    """PRD §3.8: "Supplying an `apply_credit_cents` above the cap is not silently
    clamped — it is rejected at rung 51 with `ERR_CREDIT_CAP_EXCEEDED`."
    PRD §2.9: "**Rung 51** — `apply_credit_cents`, when supplied, is at most the
    floor of half the order's `pre_credit_total_cents`. Applies to capturing a member
    order. Failure: `ERR_CREDIT_CAP_EXCEEDED`, HTTP 422."

    Design: Corner/validations/applying_more_credit_than_the_cap_returns_credit_cap_exceeded
    """
    w = canonical_world(api, "consolidated")
    grant = grant_credit(api, w, w.mara_id, 60000, "2026-12-01T00:00:00Z")

    validate_error(
        api.capture_member_order(w.order_mara, {"apply_credit_cents": 30000}, FINANCE),
        ApiErrorId.ERR_CREDIT_CAP_EXCEEDED.value,
    )

    order = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert order["payment_status"] == "AUTHORIZED"
    assert order["credit_applied_cents"] == 0

    stored = validate_success(api.get_credit_grant(grant["id"], ADMIN))
    assert stored["remaining_cents"] == 60000
    assert stored["status"] == "ACTIVE"


def test_refunding_more_than_was_captured_returns_refund_exceeds_capture(api):
    """PRD §3.8: "The `amount_cents` must be at least 1 and at most
    `captured_cents` less `refunded_cents`; outside that range the refund fails with
    `ERR_REFUND_EXCEEDS_CAPTURE`."

    Design: Corner/validations/refunding_more_than_was_captured_returns_refund_exceeds_capture
    """
    w = canonical_world(api, "captured")

    validate_error(
        api.refund_member_order(w.order_mara, refund_payload(60000, "CARD"), FINANCE),
        ApiErrorId.ERR_REFUND_EXCEEDS_CAPTURE.value,
    )

    order = validate_success(api.get_member_order(w.order_mara, FINANCE))
    assert order["refunded_cents"] == 0
    assert order["payment_status"] == "CAPTURED"

    _, meta = validate_paginated(
        api.list_payments(
            ADMIN, params={"member_order_id": w.order_mara, "kind": "REFUND"}
        )
    )
    assert meta["total_count"] == 0


# ------------------------------------------------------ the credit ledger ---
def test_an_expired_grant_is_swept_out_of_the_balance_but_keeps_its_remainder(api):
    """PRD §3.1: "Before an administrator mints a further grant, before a capture
    consumes credit, before a dues payment is applied, and before a commission payout
    is made, the server sweeps that member's grants: every grant whose `expires_at`
    the clock has reached or passed moves to `EXPIRED`."
    PRD §3.1: "An expiring grant's `remaining_cents` is left untouched as a record
    of what was forfeited, but the grant is thereafter excluded from
    `credit_balance_cents` and from every future draw."

    Design: Corner/cross_cutting_complexity_layers/an_expired_grant_is_swept_out_of_the_balance_but_keeps_its_remainder
    """
    w = build_catalog(api, items=())
    old = grant_credit(api, w, w.mara_id, 5000, "2026-06-01T00:00:00Z")
    set_clock(api, "2026-06-02T00:00:00Z")
    fresh = grant_credit(api, w, w.mara_id, 2000, "2026-12-01T00:00:00Z")

    old_after = validate_success(api.get_credit_grant(old["id"], ADMIN))
    assert old_after["status"] == "EXPIRED"
    assert old_after["remaining_cents"] == 5000

    fresh_after = validate_success(api.get_credit_grant(fresh["id"], ADMIN))
    assert fresh_after["status"] == "ACTIVE"
    assert fresh_after["remaining_cents"] == 2000

    assert validate_success(api.get_member(w.mara_id, ADMIN))["credit_balance_cents"] == 2000


def test_member_credit_balance_tracks_the_sum_of_spendable_grants(api):
    """PRD §3.1: "A member's `credit_balance_cents` is not stored independently;
    it is the sum of `remaining_cents` over that member's grants whose status is
    `ACTIVE` or `PARTIALLY_CONSUMED` and whose `expires_at` the clock has not yet
    reached."
    PRD §3.1: "The `source` is one of `VOLUNTEER`, `REFUND`, `COMMISSION` or
    `ADJUSTMENT`; a grant minted by an administrator directly carries `ADJUSTMENT`,
    and the other three are minted by the rules described later in this document."

    Design: Corner/cross_cutting_complexity_layers/member_credit_balance_tracks_the_sum_of_spendable_grants
    """
    w = build_catalog(api, items=())
    first = grant_credit(api, w, w.mara_id, 3000, "2026-12-01T00:00:00Z")
    second = grant_credit(api, w, w.mara_id, 5000, "2026-11-01T00:00:00Z")

    assert validate_success(api.get_member(w.mara_id, ADMIN))["credit_balance_cents"] == 8000
    assert validate_success(api.get_credit_grant(first["id"], ADMIN))["source"] == "ADJUSTMENT"
    assert validate_success(api.get_credit_grant(first["id"], ADMIN))["remaining_cents"] == 3000
    assert validate_success(api.get_credit_grant(second["id"], ADMIN))["remaining_cents"] == 5000

    _, meta = validate_paginated(
        api.list_credit_grants(ADMIN, params={"member_id": w.mara_id})
    )
    assert meta["total_count"] == 2
