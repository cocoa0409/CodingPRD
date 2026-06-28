"""Service pricing, member discount, wallet waterfall, and therapist commission.

Covers difficulty queue A instances on tiered-vs-flat commission and the marginal-slice
commission formula, plus corner queue B pricing/commission claims.
"""
from test_helpers import (
    validate_success,
    setup_tiered_commission_tiers,
    bookable_scenario,
    drive_to_priced,
    drive_to_paid,
    create_modality,
    create_plan,
    create_package,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_tiered_commission_marginal_slice_at_mid_band(api):
    """PRD §3.9: "Under a TIERED scheme, commission is marginal across the global commission
    schedule." PRD §3.9: "The portion of the interval from old revenue up to new revenue that
    lands inside a given tier's band is the larger of zero and (the smaller of new revenue and
    the band's upper edge) minus (the larger of old revenue and the band's lower edge); that
    slice is multiplied by the tier's commission_pct."

    With tiers 0@0.40, 20000@0.50, 40000@0.55 and old mtd 15000, a 12000 charge spans
    [15000,20000)*0.40=2000 + [20000,27000)*0.50=3500 = 5500.

    Design: Difficulty/dual_variant_calc/commission_tiered_vs_flat_on_therapist
    """
    setup_tiered_commission_tiers()
    scn = bookable_scenario(therapist_overrides={"commission_scheme": "TIERED"})
    # Prior PAID Deep-Tissue 60 (charge 15000) raises mtd to 15000.
    dt = create_modality(name="Deep Tissue Pre", code="DEEPTPRE", base_price_cents=15000)
    scn_dt = dict(scn)
    scn_dt["modality"] = dt
    drive_to_paid(scn_dt, gratuity_cents=0,
                  start_at="2026-03-02T07:00:00Z", duration_minutes=60, payer="CASH")
    # Test Swedish 60 (charge 12000) under TIERED with mtd at 15000.
    appt, _ = drive_to_priced(scn, start_at="2026-03-02T11:00:00Z", duration_minutes=60, payer="CASH")
    paid = validate_success(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT))
    assert paid["commission_credited_cents"] == 5500, \
        f"tiered marginal commission should be 5500, got {paid['commission_credited_cents']}"


def test_flat_commission_on_same_charge(api):
    """PRD §3.9: "Under a FLAT scheme, commission_credited_cents is the session's
    service_charge_cents multiplied by the therapist's flat_commission_pct, rounded half up to
    whole cents."

    A FLAT-0.40 therapist on a 12000 charge earns 4800 — divergent from the tiered payout.

    Design: Difficulty/dual_variant_calc/commission_tiered_vs_flat_on_therapist
    """
    scn = bookable_scenario(therapist_overrides={"commission_scheme": "FLAT", "flat_commission_pct": 0.40})
    appt, _ = drive_to_priced(scn, start_at="2026-03-02T11:00:00Z", duration_minutes=60, payer="CASH")
    paid = validate_success(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT))
    assert paid["commission_credited_cents"] == 4800, \
        f"flat commission should be 4800, got {paid['commission_credited_cents']}"


def test_marginal_slice_mode_a_updates_mtd_revenue(api):
    """PRD §3.9: "Let the old revenue be the therapist's mtd_service_revenue_cents before this
    session and the new revenue be that value plus this session's service_charge_cents."
    PRD §3.9: "The session's service_charge_cents is added to the therapist's
    mtd_service_revenue_cents."

    Old mtd 15000 + 12000 charge -> new mtd 27000; commission for the slice is 5500.

    Design: Difficulty/combinatorial_formula/tiered_commission_marginal_slice_mode_a
    """
    setup_tiered_commission_tiers()
    scn = bookable_scenario(therapist_overrides={"commission_scheme": "TIERED"})
    dt = create_modality(name="Deep Tissue Pre2", code="DEEPTPB", base_price_cents=15000)
    scn_dt = dict(scn)
    scn_dt["modality"] = dt
    drive_to_paid(scn_dt, gratuity_cents=0,
                  start_at="2026-03-02T07:00:00Z", duration_minutes=60, payer="CASH")
    appt, _ = drive_to_priced(scn, start_at="2026-03-02T11:00:00Z", duration_minutes=60, payer="CASH")
    paid = validate_success(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT))
    assert paid["commission_credited_cents"] == 5500
    therapist = validate_success(api.get_therapist(scn["therapist"]["id"], ADMIN))
    assert therapist["mtd_service_revenue_cents"] == 27000, \
        f"mtd should be 27000 after both sessions, got {therapist['mtd_service_revenue_cents']}"


def test_marginal_slice_single_tier_at_zero_mtd(api):
    """PRD §3.9: "Because the calculation depends on where mtd_service_revenue_cents already
    sits, the identical service_charge_cents can earn different commission on two different
    sessions."

    At old mtd 0 the whole 12000 charge sits in the first tier [0,20000)*0.40 = 4800, which is
    less than the 5500 the same charge earns at mtd 15000.

    Design: Difficulty/combinatorial_formula/tiered_commission_marginal_slice_mode_a
    """
    setup_tiered_commission_tiers()
    scn = bookable_scenario(therapist_overrides={"commission_scheme": "TIERED"})
    appt, _ = drive_to_priced(scn, start_at="2026-03-02T11:00:00Z", duration_minutes=60, payer="CASH")
    paid = validate_success(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT))
    assert paid["commission_credited_cents"] == 4800, \
        f"single-tier marginal commission at mtd 0 should be 4800, got {paid['commission_credited_cents']}"


# ---------------------------------------------------------------------------
# Corner queue B — calculations / endpoints
# ---------------------------------------------------------------------------
def test_service_pricing_cash_full_price(api):
    """PRD §3.8: "the modality's base_price_cents multiplied by duration_minutes divided by 60,
    kept exact." PRD §3.8: "(a CASH or HSA session with no active membership attached),
    service_charge_cents is simply the base value rounded half up."

    A CASH Swedish-90 (base 12000) prices to 12000 * 90/60 = 18000.

    Design: Corner/calculations/service_pricing_cash_full_price
    """
    scn = bookable_scenario()
    appt, _ = drive_to_priced(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=90, payer="CASH")
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["service_charge_cents"] == 18000
    assert fetched["client_owed_cents"] == 18000


def test_member_out_of_pocket_discount_price(api):
    """PRD §3.8: "the member discount applies: multiply the base value by one minus the plan's
    member_discount_pct, then round half up to whole cents." PRD §3.8: "For illustration, a
    12000-cent base under a 0.20 member discount yields a 9600-cent service charge."

    Design: Corner/calculations/member_out_of_pocket_discount_price
    """
    scn = bookable_scenario()
    plan = create_plan(name="DiscPlan", monthly_fee_cents=9000, included_sessions=1,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(scn["client"]["id"], plan["id"])
    appt, _ = drive_to_priced(scn, package_id=pkg["id"],
                              start_at="2026-01-05T11:00:00Z", duration_minutes=60, payer="CASH")
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["service_charge_cents"] == 9600, \
        f"member-discounted charge should be 9600, got {fetched['service_charge_cents']}"
    assert fetched["client_owed_cents"] == 9600


def test_wallet_credit_applied_in_owed_resolution(api):
    """PRD §3.8: "the amount owed begins as the service_charge_cents; the wallet contribution
    applied is the smaller of the client's wallet_credit_cents and that owed amount; the owed
    amount is reduced by the wallet contribution; and client_owed_cents is the remainder."
    PRD §3.8: "the client's wallet_credit_cents is not actually decremented until payment."

    Wallet 5000 against a 12000 charge -> client_owed 7000; wallet unchanged at PRICED.

    Design: Corner/calculations/wallet_credit_applied_in_owed_resolution
    """
    scn = bookable_scenario()
    validate_success(api.adjust_wallet(scn["client"]["id"], {"delta_cents": 5000}, ADMIN))
    appt, _ = drive_to_priced(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    fetched = validate_success(api.get_appointment(appt["id"], FRONT))
    assert fetched["service_charge_cents"] == 12000
    assert fetched["client_owed_cents"] == 7000, \
        f"client_owed after 5000 wallet should be 7000, got {fetched['client_owed_cents']}"
    client = validate_success(api.get_client(scn["client"]["id"], ADMIN))
    assert client["wallet_credit_cents"] == 5000, "wallet must not decrement until PAID"


def test_pay_credits_therapist_commission_and_gratuity(api):
    """PRD §3.9: "the commission for this session, commission_credited_cents, is computed over
    the revenue band this session occupies and added — together with the full gratuity — to the
    therapist's accrued_commission_cents." PRD §3.9: "Gratuity is paid to the therapist in full
    but is deliberately excluded from the commission base."

    FLAT-0.40 on a 12000 charge with gratuity 1500 -> commission 4800, accrued 4800+1500=6300.

    Design: Corner/endpoints/pay_credits_therapist_commission_and_gratuity
    """
    scn = bookable_scenario(therapist_overrides={"commission_scheme": "FLAT", "flat_commission_pct": 0.40})
    appt, _ = drive_to_priced(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    paid = validate_success(api.pay_appointment(appt["id"], {"gratuity_cents": 1500}, FRONT))
    assert paid["commission_credited_cents"] == 4800
    assert paid["settlement_status"] == "PAID"
    therapist = validate_success(api.get_therapist(scn["therapist"]["id"], ADMIN))
    assert therapist["accrued_commission_cents"] == 6300, \
        f"accrued should be commission 4800 + gratuity 1500 = 6300, got {therapist['accrued_commission_cents']}"
    assert therapist["mtd_service_revenue_cents"] == 12000


def test_reset_commission_zeroes_accumulators(api):
    """PRD §3.1: "A PracticeAdmin may begin a fresh commission month by resetting the
    therapist's accumulators, which sets both mtd_service_revenue_cents and
    accrued_commission_cents back to 0 and bumps the therapist's version."

    Design: Corner/endpoints/reset_commission_zeroes_accumulators
    """
    scn = bookable_scenario(therapist_overrides={"commission_scheme": "FLAT", "flat_commission_pct": 0.40})
    drive_to_paid(scn, gratuity_cents=0, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    reset = validate_success(api.reset_commission(scn["therapist"]["id"], ADMIN))
    assert reset["mtd_service_revenue_cents"] == 0
    assert reset["accrued_commission_cents"] == 0


def test_pay_response_reflects_all_mutations_immediately(api):
    """PRD §3.9: "Payment then moves settlement_status to PAID." PRD §3.9: "the commission for
    this session, commission_credited_cents, is computed over the revenue band this session
    occupies and added — together with the full gratuity — to the therapist's
    accrued_commission_cents."

    The pay response shows PAID + commission immediately; a later GET on the therapist shows the
    updated accrued total.

    Design: Corner/consistency_model/pay_response_reflects_all_mutations_immediately
    """
    scn = bookable_scenario(therapist_overrides={"commission_scheme": "FLAT", "flat_commission_pct": 0.40})
    appt, _ = drive_to_priced(scn, start_at="2026-01-05T09:00:00Z", duration_minutes=60, payer="CASH")
    paid = validate_success(api.pay_appointment(appt["id"], {"gratuity_cents": 0}, FRONT))
    assert paid["settlement_status"] == "PAID"
    assert paid["commission_credited_cents"] == 4800
    therapist = validate_success(api.get_therapist(scn["therapist"]["id"], ADMIN))
    assert therapist["accrued_commission_cents"] == 4800
