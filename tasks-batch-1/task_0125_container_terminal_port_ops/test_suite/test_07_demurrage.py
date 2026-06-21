"""Demurrage accrual and invoicing: the marginal tiered day-bucket rule, the
exclusive free-time boundary, the on-demand quote, and invoice pay/waive.

Difficulty instances: dual_variant_calc (chronological_billed straddles tiers),
combinatorial_formula (tiered marginal rate, non-linear),
boundary_precision_check (zero at exact free-time expiry). Corner instances:
one-second-past bills one day, three days within tier 1, zero before berth,
invoice pay, invoice waive.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["terminal_admin_headers"]
GATE = TEST_USERS["gate_operator_headers"]


# --------------------------------------------------------------------------- #
# Marginal tiered rate straddling a tier boundary — dual_variant / combinatorial
# --------------------------------------------------------------------------- #
def test_demurrage_quote_8_days_straddles_tiers(api):
    """PRD §3.6: "The first three chargeable days each bill at the first-tier rate
    of 5000 cents; the next four chargeable days (days four through seven) each bill
    at the second-tier rate of 8000 cents; every chargeable day beyond the seventh
    bills at the third-tier rate of 12000 cents. The charge is therefore marginal,
    not blended".

    Design: Difficulty/combinatorial_formula/demurrage_tiered_marginal_rate_nonlinear
    """
    # berth 2026-02-01, free_time_days=5 => free expires 2026-02-06; clock 2026-02-13T12:00 => 7d12h => 8 days.
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-13T12:00:00.000Z",
        cleared=False,
    )
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    assert data["chargeable_days"] == 8
    assert data["demurrage_due_cents"] == 59000  # 3*5000 + 4*8000 + 1*12000


def test_demurrage_invoice_frozen_at_59000_on_gateout(api):
    """PRD §3.6: "At **gate-out**, the same computation runs and its outcome is
    frozen onto a newly issued **demurrage invoice**: the invoice ... copies the
    computed `chargeable_days`, freezes the computed `amount_cents`".

    Design: Difficulty/dual_variant_calc/demurrage_chronological_billed_straddles_tiers
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-13T12:00:00.000Z",
        cleared=True,
    )
    fx.gate_out_container(
        container["id"],
        window_start="2026-02-13T12:00:00.000Z",
        window_end="2026-02-13T13:00:00.000Z",
        check_in_clock="2026-02-13T12:00:00.000Z",
    )
    cont_after = validate_success(api.get_container(container["id"], GATE), 200)
    assert cont_after["demurrage_due_cents"] == 59000
    invoice = fx.get_only_invoice(container["id"])
    assert invoice["amount_cents"] == 59000
    assert invoice["chargeable_days"] == 8


def test_demurrage_quote_8_days_returns_chargeable_days(api):
    """PRD §3.6: "When the as-of instant is past free-time expiry, the rule counts
    chargeable days as the elapsed time from `free_time_expires_at` to the as-of
    instant, divided into whole twenty-four-hour day buckets, with any partial day
    rounded **up** to a full day".

    Design: Difficulty/dual_variant_calc/demurrage_chronological_billed_straddles_tiers
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-13T12:00:00.000Z",
        cleared=False,
    )
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    assert data["chargeable_days"] == 8
    assert data["demurrage_due_cents"] == 59000


def test_demurrage_quote_8_days_nonlinear_not_blended(api):
    """PRD §3.6: "a fourth chargeable day bills at the second-tier rate even though
    the first three billed at the first tier, and the total is the sum across all
    chargeable days of each day's own tier rate."

    Design: Difficulty/combinatorial_formula/demurrage_tiered_marginal_rate_nonlinear
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-13T12:00:00.000Z",
        cleared=False,
    )
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    # A blended estimate (8 * average) would never equal the marginal 59000 exactly.
    assert data["demurrage_due_cents"] == 59000


# --------------------------------------------------------------------------- #
# Exclusive free-time boundary — boundary_precision_check
# --------------------------------------------------------------------------- #
def test_demurrage_zero_at_exact_free_time_expiry(api):
    """PRD §3.6: "if the as-of instant is at or before `free_time_expires_at`, the
    container is still inside free time and owes zero (the boundary is exclusive, so
    a container quoted or gated out exactly at `free_time_expires_at` owes nothing)."

    Design: Difficulty/boundary_precision_check/demurrage_zero_at_exact_free_time_expiry
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-06T00:00:00.000Z",  # exactly at expiry
        cleared=False,
    )
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    assert data["chargeable_days"] == 0
    assert data["demurrage_due_cents"] == 0


def test_demurrage_one_second_past_bills_one_day(api):
    """PRD §3.6: "any partial day rounded **up** to a full day — so eleven hours
    past expiry counts as one chargeable day". PRD §3.6: "The first three chargeable
    days each bill at the first-tier rate of 5000 cents".

    Design: Difficulty/boundary_precision_check/demurrage_zero_at_exact_free_time_expiry
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-06T00:00:01.000Z",  # one second past expiry
        cleared=False,
    )
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    assert data["chargeable_days"] == 1
    assert data["demurrage_due_cents"] == 5000


def test_demurrage_one_second_past_free_time_bills_one_day_corner(api):
    """PRD §3.6: "any partial day rounded **up** to a full day". PRD §3.6: "The
    first three chargeable days each bill at the first-tier rate of 5000 cents".

    Design: Corner/calculations/demurrage_one_second_past_free_time_bills_one_day
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-06T00:00:01.000Z",
        cleared=False,
    )
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    assert data["chargeable_days"] == 1
    assert data["demurrage_due_cents"] == 5000


def test_demurrage_three_days_within_tier1(api):
    """PRD §3.6: "The first three chargeable days each bill at the first-tier rate
    of 5000 cents".

    Design: Corner/calculations/demurrage_three_days_within_tier1
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-09T00:00:00.000Z",  # exactly 3 days past free
        cleared=False,
    )
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    assert data["chargeable_days"] == 3
    assert data["demurrage_due_cents"] == 15000


def test_demurrage_zero_before_berth_when_free_time_null(api):
    """PRD §3.6: "The rule begins from the container's `free_time_expires_at`: if
    that instant is null — meaning the discharge window has not yet berthed — the
    charge is zero."

    Design: Corner/calculations/demurrage_zero_before_berth_when_free_time_null
    """
    fx.set_clock("2027-01-01T00:00:00.000Z")
    berth = fx.provision_berth(code="B-450", length_m=300, draft_m=14.0)
    vessel = fx.provision_vessel(imo_number="2000250", name="Nul V", loa_m=280, draft_m=13.0, free_time_days=5)
    window = fx.create_scheduled_window(berth["id"], vessel["id"], etd="2026-02-25T00:00:00.000Z")
    container = fx.declare_container(vessel["id"], window["id"], container_number="NULF450450")
    data = validate_success(api.get_demurrage_quote(container["id"], GATE), 200)
    assert data["demurrage_due_cents"] == 0
    assert data["chargeable_days"] == 0


# --------------------------------------------------------------------------- #
# Invoice pay / waive
# --------------------------------------------------------------------------- #
def test_invoice_pay_transitions_issued_to_paid(api):
    """PRD §3.6: "A `TerminalAdmin` later settles an invoice by **paying** it
    (moving `ISSUED` to the terminal `PAID`) ... either action requires the invoice
    to be `ISSUED`, otherwise `ERR_INVALID_STATE`".

    Design: Corner/endpoints/invoice_pay_transitions_issued_to_paid
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-13T12:00:00.000Z",
        cleared=True,
    )
    fx.gate_out_container(
        container["id"],
        window_start="2026-02-13T12:00:00.000Z",
        window_end="2026-02-13T13:00:00.000Z",
        check_in_clock="2026-02-13T12:00:00.000Z",
    )
    invoice = fx.get_only_invoice(container["id"])
    data = validate_success(api.pay_demurrage_invoice(invoice["id"], ADMIN), 200)
    assert data["status"] == "PAID"
    assert data["amount_cents"] == 59000


def test_invoice_waive_transitions_issued_to_waived(api):
    """PRD §3.6: "A `TerminalAdmin` later settles an invoice by ... **waiving** it
    (moving `ISSUED` to the terminal `WAIVED`); either action requires the invoice
    to be `ISSUED`, otherwise `ERR_INVALID_STATE`".

    Design: Corner/endpoints/invoice_waive_transitions_issued_to_waived
    """
    _, _, container, _ = fx.setup_container_for_demurrage(
        berth_at="2026-02-01T00:00:00.000Z",
        free_time_days=5,
        as_of_clock="2026-02-13T12:00:00.000Z",
        cleared=True,
    )
    fx.gate_out_container(
        container["id"],
        window_start="2026-02-13T12:00:00.000Z",
        window_end="2026-02-13T13:00:00.000Z",
        check_in_clock="2026-02-13T12:00:00.000Z",
    )
    invoice = fx.get_only_invoice(container["id"])
    data = validate_success(api.waive_demurrage_invoice(invoice["id"], ADMIN), 200)
    assert data["status"] == "WAIVED"
