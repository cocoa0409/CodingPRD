"""Storage billing: renewal proration vs lapse, rounding order, lapse cycle.

Queue-A (Difficulty) translations for dual_variant_calc (renewal vs lapse
divergence), combinatorial_formula (proration rounding order), and
non_linear_state_machine (lapse reactivation cycle).
"""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_shipped_reservation, setup_lapsed_account,
)

BC = TEST_USERS["billing_clerk_headers"]


def _find_invoice(invoices, billing_mode=None, period_index=None):
    for inv in invoices:
        if billing_mode is not None and inv["billing_mode"] != billing_mode:
            continue
        if period_index is not None and inv["period_index"] != period_index:
            continue
        return inv
    return None


def test_period0_renewal_full_base_and_early_renewal_prorated(api):
    """PRD §3.7: "The charge for one full billing period is the account's
    stored_vials multiplied by the annual per-vial rate of 42000 cents". PRD §3.7:
    "The first invoice at period_index 0, issued at dispatch, is a special case of
    the RENEWAL mode covering a full period — its remaining days equal the full 365,
    so its charge equals the base exactly." PRD §3.7: "Let the elapsed whole days be
    the number of days from the account's period_start to the renewal instant, taken
    as a floor to whole days; let the remaining days be 365 minus those elapsed days.
    The renewal charge is the base charge multiplied by the remaining days and
    divided by 365, rounded half-up to whole cents."

    stored_vials=2 -> base 84000. Renewal at +100 days: remaining 265,
    84000*265/365 = 60986.30 -> round_half_up 60986.

    Design: Difficulty/dual_variant_calc/storage_bill_renewal_vs_lapse_diverge
    """
    ctx = setup_shipped_reservation(display_code="D-1", dewar_code="T-1",
                                    vial_count=2, ship_clock="2026-06-01T00:00:00Z")
    invoices = validate_success(api.list_storage_invoices(
        BC, params={"storage_account_id": ctx["storage_account_id"]}))
    period0 = _find_invoice(invoices, billing_mode="RENEWAL", period_index=0)
    assert period0 is not None, "period-0 RENEWAL invoice must exist"
    assert period0["amount_cents"] == 84000, "full first period = base"
    # Early-renew 100 days into the period.
    validate_success(api.set_clock("2026-09-09T00:00:00Z", BC))
    renew_inv = validate_success(api.renew_account(ctx["storage_account_id"], BC))
    assert renew_inv["billing_mode"] == "RENEWAL"
    assert renew_inv["amount_cents"] == 60986, "84000 * 265/365 round_half_up = 60986"


def test_renewal_charge_strictly_below_lapse_on_identical_data(api):
    """PRD §3.7: "once at least one whole day has elapsed, the `RENEWAL` charge is
    strictly smaller than the `LAPSE` charge." PRD §3.7: "Under the `LAPSE` mode, no
    proration applies: the charge is simply the base for the full period regardless
    of how many days have elapsed."

    Same stored_vials=2 (base 84000): a RENEWAL at +100 days is 60986; a LAPSE would
    charge the full 84000. RENEWAL (60986) < LAPSE base (84000).

    Design: Difficulty/dual_variant_calc/storage_bill_renewal_vs_lapse_diverge
    """
    ctx = setup_shipped_reservation(display_code="D-1b", dewar_code="T-1b",
                                    vial_count=2, ship_clock="2026-06-01T00:00:00Z")
    validate_success(api.set_clock("2026-09-09T00:00:00Z", BC))
    renew_inv = validate_success(api.renew_account(ctx["storage_account_id"], BC))
    assert renew_inv["billing_mode"] == "RENEWAL"
    assert renew_inv["amount_cents"] == 60986
    assert renew_inv["amount_cents"] < 84000, "prorated RENEWAL strictly below full base"


def test_renewal_proration_rounding_multiplies_before_dividing(api):
    """PRD §3.7: "The renewal charge is the base charge multiplied by the remaining
    days and divided by 365, rounded half-up to whole cents." PRD §2.8: "the result
    is rounded to the nearest whole cent using the round-half-up convention (a value
    exactly halfway between two cents rounds up)."

    84000 * 265 / 365 = 60986.301... -> round_half_up -> 60986 (multiply-then-divide
    then round once; a per-vial or reordered computation would drift off 60986).

    Design: Difficulty/combinatorial_formula/renewal_proration_rounding_order
    """
    ctx = setup_shipped_reservation(display_code="D-3", dewar_code="T-3",
                                    vial_count=2, ship_clock="2026-06-01T00:00:00Z")
    validate_success(api.set_clock("2026-09-09T00:00:00Z", BC))
    renew_inv = validate_success(api.renew_account(ctx["storage_account_id"], BC))
    assert renew_inv["amount_cents"] == 60986


def test_period0_invoice_no_rounding_equals_base_exactly(api):
    """PRD §3.7: "The first invoice at period_index 0, issued at dispatch, is a
    special case of the RENEWAL mode covering a full period — its remaining days
    equal the full 365, so its charge equals the base exactly."

    remaining=365 -> 84000*365/365 = 84000 exactly (no fractional cent to round).

    Design: Difficulty/combinatorial_formula/renewal_proration_rounding_order
    """
    ctx = setup_shipped_reservation(display_code="D-3b", dewar_code="T-3b",
                                    vial_count=2, ship_clock="2026-06-01T00:00:00Z")
    invoices = validate_success(api.list_storage_invoices(
        BC, params={"storage_account_id": ctx["storage_account_id"]}))
    period0 = _find_invoice(invoices, billing_mode="RENEWAL", period_index=0)
    assert period0 is not None
    assert period0["amount_cents"] == 84000, "remaining=365 -> base exactly, no rounding"


def test_assess_lapse_moves_active_account_to_lapsed(api):
    """PRD §3.7: "A BillingClerk may also assess a lapse, advancing the account
    ACTIVE -> LAPSED. Assessment requires that the account be ACTIVE and that the
    current logical time has reached or passed paid_through plus the grace period of
    30 days".

    Design: Difficulty/non_linear_state_machine/storage_account_lapse_reactivation_cycle
    """
    ctx = setup_lapsed_account(display_code="D-6b", dewar_code="T-6b", vial_count=2,
                               ship_clock="2026-06-01T00:00:00Z",
                               lapse_clock="2027-07-01T00:00:00Z")
    account = validate_success(api.get_storage_account(ctx["storage_account_id"], BC))
    assert account["status"] == "LAPSED", "assess-lapse drove ACTIVE -> LAPSED"


def test_lapse_invoice_is_full_base_and_pay_restores_active(api):
    """PRD §3.7: "A successful assessment issues a LAPSE invoice for the full unpaid
    period." PRD §3.7: "Under the LAPSE mode, no proration applies: the charge is
    simply the base for the full period regardless of how many days have elapsed."
    PRD §3.7: "When the invoice being paid is the LAPSE invoice on a LAPSED account
    ..., paying it also advances paid_through by one billing period and restores the
    account LAPSED -> ACTIVE."

    Design: Difficulty/non_linear_state_machine/storage_account_lapse_reactivation_cycle
    """
    ctx = setup_lapsed_account(display_code="D-6", dewar_code="T-6", vial_count=2,
                               ship_clock="2026-06-01T00:00:00Z",
                               lapse_clock="2027-07-01T00:00:00Z")
    account = validate_success(api.get_storage_account(ctx["storage_account_id"], BC))
    assert account["status"] == "LAPSED"
    paid = validate_success(api.pay_invoice(ctx["lapse_invoice_id"], BC))
    assert paid["status"] == "PAID"
    assert paid["billing_mode"] == "LAPSE"
    assert paid["amount_cents"] == 84000, "LAPSE = full base for stored_vials=2"
    account = validate_success(api.get_storage_account(ctx["storage_account_id"], BC))
    assert account["status"] == "ACTIVE", "lapse pay restores account to ACTIVE"
