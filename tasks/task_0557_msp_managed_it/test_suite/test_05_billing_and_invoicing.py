"""Billing math: PROVISIONAL vs FINAL invoices, tiered volume discount + add-ons,
overage accrual, and the round-per-line-then-sum rounding rule."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_client,
    create_contract,
    activate_contract,
    create_technician,
    create_ticket,
    assign_ticket,
    create_dispatch,
    complete_dispatch,
    create_seat_adjustment,
    create_invoice,
    create_procurement_order,
    create_quote,
    setup_active_contract,
    setup_contract_with_seat_adjustment,
)


SM = "service_manager_headers"


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / contract_seat_charge_provisional_vs_final
# ---------------------------------------------------------------------------

def test_provisional_invoice_uses_current_seat_snapshot_full_period(api):
    """PRD §3.8: "For a `PROVISIONAL` invoice, `seat_count_snapshot` is the
    contract's current `seat_count`, `total_seat_days` is 0, and
    `base_seat_charge_cents` is `seat_count_snapshot` multiplied by
    `per_seat_rate_cents` — the full-period rate on the current seat level,
    ignoring any intra-period seat changes."
    PRD §3.8: "The `volume_discount_cents` is `base_seat_charge_cents`
    multiplied by a discount rate selected from the seat snapshot by inclusive
    lower bound — 0.00 for a snapshot of 1 through 9 seats, 0.05 for 10 through
    24, 0.10 for 25 through 49, and 0.15 for 50 or more"

    Design: Difficulty/dual_variant_calc/contract_seat_charge_provisional_vs_final
    """
    # Contract activated 2026-06-01, seat_count 10 rate 5000, +10 mid-period at 06-16
    # (so current seat_count is 20 at PROVISIONAL time). PROVISIONAL: base = 20*5000
    # = 100000; discount tier for 20 seats = 0.05 ⇒ discount 5000; total = 95000.
    _, contract, _ = setup_contract_with_seat_adjustment(
        seat_count=10, per_seat_rate_cents=5000,
        service_tier="SILVER",
        activate_clock="2026-06-01T00:00:00Z",
        adjustment_effective_at="2026-06-16T00:00:00Z",
        adjustment_delta=10,
    )
    # Advance clock mid-period so the current seat_count (20) is the snapshot.
    set_clock("2026-06-20T00:00:00Z")
    inv = validate_success(
        api.create_invoice(contract["id"], {"variant": "PROVISIONAL"},
                           TEST_USERS[SM]),
        expected_status=201,
    )
    assert inv["seat_count_snapshot"] == 20
    assert inv["base_seat_charge_cents"] == 100000
    assert inv["total_cents"] == 95000


def test_final_invoice_prorates_by_seat_days(api):
    """PRD §3.8: "For a `FINAL` invoice, the seat level is prorated across the
    period by seat-days. Walk the seat timeline over the period: begin at the
    seat level in force at `period_start`, then apply, in order of `effective_at`
    ascending with `created_at` ascending as the tie-break, every
    `SeatAdjustment` whose `effective_at` falls within the half-open period
    `[period_start, period_end)`. For each resulting sub-interval, accrue that
    sub-interval's seat level multiplied by its whole number of days;
    `total_seat_days` is the sum of those seat-days. For the FINAL variant,
    `seat_count_snapshot` is the seat level in force at `period_end`, and
    `base_seat_charge_cents` is `per_seat_rate_cents` multiplied by
    `total_seat_days`, divided by 30 (the period length in days), rounded half
    up to whole cents."

    Design: Difficulty/dual_variant_calc/contract_seat_charge_provisional_vs_final
    """
    # Same setup: activate 06-01 seat_count 10; +10 at 06-16 → seat_count 20.
    # Period 06-01..07-01 (30 days).
    # Sub-interval 1: 06-01..06-16 = 15 days at 10 seats = 150 seat-days.
    # Sub-interval 2: 06-16..07-01 = 15 days at 20 seats = 300 seat-days.
    # total_seat_days = 450. base = 5000 * 450 / 30 = 75000.
    # seat_count_snapshot at period_end = 20 → discount tier 0.05 ⇒ 3750.
    # total = 75000 - 3750 = 71250.
    _, contract, _ = setup_contract_with_seat_adjustment(
        seat_count=10, per_seat_rate_cents=5000,
        service_tier="SILVER",
        activate_clock="2026-06-01T00:00:00Z",
        adjustment_effective_at="2026-06-16T00:00:00Z",
        adjustment_delta=10,
    )
    set_clock("2026-07-01T00:00:00Z")
    inv = validate_success(
        api.create_invoice(contract["id"], {"variant": "FINAL"}, TEST_USERS[SM]),
        expected_status=201,
    )
    assert inv["total_seat_days"] == 450
    assert inv["base_seat_charge_cents"] == 75000
    assert inv["total_cents"] == 71250


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / invoice_total_tiered_discount_and_addons
# ---------------------------------------------------------------------------

def test_invoice_base_charge_and_volume_discount_at_25_49_tier(api):
    """PRD §3.8: "For a `PROVISIONAL` invoice, `seat_count_snapshot` is the
    contract's current `seat_count`, `total_seat_days` is 0, and
    `base_seat_charge_cents` is `seat_count_snapshot` multiplied by
    `per_seat_rate_cents`"
    PRD §3.8: "The `volume_discount_cents` is `base_seat_charge_cents`
    multiplied by a discount rate selected from the seat snapshot by inclusive
    lower bound — 0.00 for a snapshot of 1 through 9 seats, 0.05 for 10 through
    24, 0.10 for 25 through 49, and 0.15 for 50 or more — with the product
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_discount_and_addons
    """
    set_clock("2026-06-01T00:00:00Z")
    client, contract = setup_active_contract(
        client_overrides={"company_name": "Gamma",
                          "primary_contact_email": "g@gamma.test"},
        contract_overrides={"service_tier": "SILVER",
                            "seat_count": 30, "per_seat_rate_cents": 5000,
                            "backup_addon": True, "security_addon": True},
    )
    inv = create_invoice(contract["id"], "PROVISIONAL")
    assert inv["base_seat_charge_cents"] == 150000  # 30 * 5000
    assert inv["volume_discount_cents"] == 15000     # 150000 * 0.10 (tier [25,49])


def test_invoice_addon_charge_and_total_with_backup_and_security(api):
    """PRD §3.8: "The `addon_charge_cents` adds a per-seat surcharge for each
    enabled add-on: 800 cents per seat when `backup_addon` is enabled plus 1500
    cents per seat when `security_addon` is enabled, each multiplied by
    `seat_count_snapshot`."
    PRD §3.8: "Finally, the invoice's `total_cents` is `base_seat_charge_cents`,
    minus `volume_discount_cents`, plus `addon_charge_cents`, plus
    `overage_charge_cents`."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_discount_and_addons
    """
    set_clock("2026-06-01T00:00:00Z")
    client, contract = setup_active_contract(
        client_overrides={"company_name": "Gamma2",
                          "primary_contact_email": "g2@gamma.test"},
        contract_overrides={"service_tier": "SILVER",
                            "seat_count": 30, "per_seat_rate_cents": 5000,
                            "backup_addon": True, "security_addon": True},
    )
    inv = create_invoice(contract["id"], "PROVISIONAL")
    # 30 * 800 + 30 * 1500 = 24000 + 45000 = 69000
    assert inv["addon_charge_cents"] == 69000
    assert inv["overage_charge_cents"] == 0
    # total = 150000 - 15000 + 69000 + 0 = 204000
    assert inv["total_cents"] == 204000


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / procurement_total_round_per_line_then_sum
# ---------------------------------------------------------------------------

def test_procurement_total_round_per_line_after_tax_then_sum(api):
    """PRD §2.9: "Tax is applied per line item and rounded per line item
    before the lines are summed; the alternative of summing pre-tax then
    rounding once is not used and may differ by a cent."
    PRD §3.7: "The order's read-only `total_cents` is computed by the same
    per-line, round-then-sum rule as a quote."

    Design: Difficulty/combinatorial_formula/procurement_total_round_per_line_then_sum
    """
    client = create_client(
        company_name="Delta", primary_contact_email="d@delta.test",
        credit_limit_cents=1_000_000,
    )
    resp = api.create_procurement_order(
        {"client_id": client["id"],
         "line_items": [
             {"description": "cable", "unit_price_cents": 333, "qty": 1},
             {"description": "clip", "unit_price_cents": 334, "qty": 1},
         ],
         "tax_rate": 0.10},
        TEST_USERS["account_manager_headers"],
    )
    data = validate_success(resp, expected_status=201)
    # 333 * 1.10 = 366.3 → round_half_up → 366
    # 334 * 1.10 = 367.4 → round_half_up → 367
    # sum = 733; sum-then-round would give round(667*1.10) = round(733.7) = 734
    assert data["total_cents"] == 733


def test_procurement_total_diverges_from_sum_then_round(api):
    """PRD §2.9: "Tax is applied per line item and rounded per line item before
    the lines are summed; the alternative of summing pre-tax then rounding once
    is not used and may differ by a cent."

    Design: Difficulty/combinatorial_formula/procurement_total_round_per_line_then_sum
    """
    client = create_client(
        company_name="Delta2", primary_contact_email="d2@delta.test",
        credit_limit_cents=1_000_000,
    )
    resp = api.create_procurement_order(
        {"client_id": client["id"],
         "line_items": [
             {"description": "cable", "unit_price_cents": 333, "qty": 1},
             {"description": "clip", "unit_price_cents": 334, "qty": 1},
         ],
         "tax_rate": 0.10},
        TEST_USERS["account_manager_headers"],
    )
    data = validate_success(resp, expected_status=201)
    assert data["total_cents"] != 734  # confirms per-line-then-sum, not sum-then-round


# ---------------------------------------------------------------------------
# Queue B: calculations / quote_total_round_per_line_then_sum
# ---------------------------------------------------------------------------

def test_quote_subtotal_and_total_round_per_line_then_sum(api):
    """PRD §3.7: "Two read-only money figures are computed at write time:
    `subtotal_cents` is the sum over the line items of `unit_price_cents`
    multiplied by `qty` (pre-tax); `total_cents` is computed line by line —
    for each line, take `unit_price_cents` multiplied by `qty`, multiply by
    one plus the `tax_rate`, and round that line half up to whole cents —
    and only then sum the rounded lines."

    Design: Corner/calculations/quote_total_round_per_line_then_sum
    """
    client = create_client(company_name="Iot", primary_contact_email="i@iot.test")
    resp = api.create_quote(
        {"client_id": client["id"], "quote_type": "PROCUREMENT", "title": "q",
         "line_items": [
             {"description": "a", "unit_price_cents": 500, "qty": 2},
             {"description": "b", "unit_price_cents": 333, "qty": 1},
         ],
         "tax_rate": 0.08,
         "valid_until": "2026-12-31T00:00:00Z"},
        TEST_USERS["account_manager_headers"],
    )
    data = validate_success(resp, expected_status=201)
    # subtotal = 1000 + 333 = 1333
    # line 1: 1000 * 1.08 = 1080 → 1080
    # line 2: 333 * 1.08 = 359.64 → 360 (round_half_up)
    # total = 1080 + 360 = 1440
    assert data["subtotal_cents"] == 1333
    assert data["total_cents"] == 1440


# ---------------------------------------------------------------------------
# Queue B: calculations / invoice_overage_charge_from_accrued_ticket_minutes
# ---------------------------------------------------------------------------

def test_invoice_overage_charge_and_total_with_accrued_ticket_minutes(api):
    """PRD §3.8: "The `overage_charge_cents` bills ticket labor beyond what the
    tier includes: the included allowance is 600 minutes for `BRONZE`, 1200 for
    `SILVER`, and 3000 for `GOLD`, the overage is the greater of zero and the
    contract's `period_ticket_minutes` minus that allowance, and the charge is
    that overage multiplied by 250 cents per minute."

    Design: Corner/calculations/invoice_overage_charge_from_accrued_ticket_minutes
    """
    set_clock("2026-05-01T00:00:00Z")
    client, contract = setup_active_contract(
        client_overrides={"company_name": "Kap",
                          "primary_contact_email": "k@kap.test"},
        contract_overrides={"service_tier": "SILVER", "seat_count": 10,
                            "per_seat_rate_cents": 5000},
    )
    tech = create_technician(full_name="T3", hourly_rate_cents=8000)
    ticket = create_ticket(client["id"], contract["id"], priority="P1", subject="outage")
    ticket = assign_ticket(ticket["id"], tech["id"])
    dispatch = create_dispatch(
        ticket["id"], tech["id"], mode="REMOTE",
        scheduled_start="2026-05-01T02:00:00Z",
        scheduled_end="2026-05-01T04:00:00Z",
        resolves_ticket=True,
    )
    complete_dispatch(dispatch["id"], tech["id"], logged_minutes=1500)
    inv = create_invoice(contract["id"], "PROVISIONAL")
    # SILVER included 1200; period_ticket_minutes 1500 → overage 300 * 250 = 75000
    assert inv["overage_charge_cents"] == 75000
    # base = 10 * 5000 = 50000; discount tier for 10 → 0.05 ⇒ 2500;
    # addon = 0 (no add-ons); total = 50000 - 2500 + 0 + 75000 = 122500
    assert inv["total_cents"] == 122500


# ---------------------------------------------------------------------------
# Queue B: validations / credit_limit_exceeded_standalone_returns_402
# ---------------------------------------------------------------------------

def test_place_order_exceeding_credit_limit_returns_credit_limit_exceeded(api):
    """PRD §3.7: "The order's `total_cents` must not exceed the client's
    `credit_available_cents` at place time; an order that would breach the
    ceiling is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_exceeded_standalone_returns_402
    """
    client = create_client(
        company_name="Rho", primary_contact_email="r@rho.test",
        credit_limit_cents=100,
    )
    order = create_procurement_order(
        client["id"],
        line_items=[{"description": "laptop", "unit_price_cents": 50000, "qty": 1}],
    )
    resp = api.place_procurement_order(
        order["id"], TEST_USERS["account_manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


# ---------------------------------------------------------------------------
# Queue B: validations / place_order_unaccepted_quote_standalone_returns_409
# ---------------------------------------------------------------------------

def test_place_order_linked_to_sent_quote_returns_quote_not_accepted(api):
    """PRD §3.7: "If a `quote_id` is linked, that quote must be `ACCEPTED`,
    otherwise the place is rejected with `ERR_QUOTE_NOT_ACCEPTED`."

    Design: Corner/validations/place_order_unaccepted_quote_standalone_returns_409
    """
    from test_helpers import send_quote
    client = create_client(
        company_name="Sig", primary_contact_email="s@sig.test",
        credit_limit_cents=10_000_000,
    )
    quote = create_quote(
        client["id"], "PROCUREMENT",
        line_items=[{"description": "laptop", "unit_price_cents": 50000, "qty": 1}],
    )
    send_quote(quote["id"])
    order = create_procurement_order(
        client["id"],
        line_items=[{"description": "laptop", "unit_price_cents": 50000, "qty": 1}],
        quote_id=quote["id"],
    )
    resp = api.place_procurement_order(
        order["id"], TEST_USERS["account_manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED)


# Queue B: validations / empty_line_items_on_procurement_returns_422 — SKIPPED
# under the PRD-first filter. PRD §3.7 wires ERR_EMPTY_LINE_ITEMS explicitly to
# the quote /send path only ("its `line_items` to be non-empty (otherwise
# `ERR_EMPTY_LINE_ITEMS`)"). For procurement create §3.7 says only "a
# non-empty `line_items` array" without naming the specific error id — a
# faithful PRD-only implementer could equally ship ERR_VALIDATION. No test
# emitted.
