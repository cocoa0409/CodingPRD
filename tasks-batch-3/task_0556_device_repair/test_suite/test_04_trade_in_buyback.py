"""Trade-in buyback: quoted-vs-final payout, round-then-sum payout arithmetic, the
dispute re-grade loop, the store-credit conservation invariant, and the payout guards.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_customer_headers, make_technician_headers,
    create_customer, create_device, create_technician,
    setup_trade_in_submitted, setup_trade_in_offer_made, setup_trade_in_accepted,
    offer_trade_in, issue_wipe_certificate,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["store_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / tradein_quoted_vs_final_payout
# ---------------------------------------------------------------------------
def test_tradein_quoted_payout_from_declared_grade(api):
    """PRD §3.7: "A graded value is the base multiplied by the grade multiplier —
    0.90 for grade `A`, 0.70 for `B`, 0.45 for `C`, and 0.20 for `D` — rounded half-up
    to whole cents."
    PRD §3.7: "For the submission quote, the grade is the `declared_grade`, no accessory
    bonus applies, and there are no cosmetic deductions, so `quoted_payout_cents`
    reflects grade alone."

    Design: Difficulty/dual_variant_calc/tradein_quoted_vs_final_payout
    """
    scn = setup_trade_in_submitted(market_value_cents=99010, declared_grade="A")
    assert scn["trade_in"]["quoted_payout_cents"] == 89109


def test_tradein_final_payout_diverges_from_quoted(api):
    """PRD §3.7: "`final_payout_cents` is computed by the same payout formula, now using
    the assessed grade with the accessory bonus and cosmetic deductions applied; the
    final payout may therefore diverge from the quoted one."

    Design: Difficulty/dual_variant_calc/tradein_quoted_vs_final_payout
    """
    scn = setup_trade_in_submitted(market_value_cents=99010, declared_grade="A")
    quoted = scn["trade_in"]["quoted_payout_cents"]
    offered = offer_trade_in(scn, "C", has_accessories=False, assessed_cosmetic_defect_count=0)
    assert offered["final_payout_cents"] == 44555
    assert offered["final_payout_cents"] != quoted


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / tradein_payout_round_then_sum
# ---------------------------------------------------------------------------
def test_tradein_payout_round_each_component_then_sum(api):
    """PRD §3.7: "The payout is the graded value plus the accessory bonus minus the
    cosmetic deduction multiplied by the defect count; each of the three components is
    rounded to whole cents before they are combined, not after."

    Design: Difficulty/combinatorial_formula/tradein_payout_round_then_sum
    """
    # market 99010, grade C, accessories, 1 defect:
    # round(44554.5)=44555 + round(4950.5)=4951 - round(2970.3)=2970 = 46536 (not 46535).
    scn = setup_trade_in_submitted(market_value_cents=99010, declared_grade="C")
    offered = offer_trade_in(scn, "C", has_accessories=True, assessed_cosmetic_defect_count=1)
    assert offered["final_payout_cents"] == 46536


def test_tradein_payout_accessory_bonus_rounded_before_sum(api):
    """PRD §3.7: "An accessory bonus is the base multiplied by 0.05, rounded half-up,
    but only when the accessory flag is set, and 0 otherwise."
    PRD §3.7: "each of the three components is rounded to whole cents before they are
    combined, not after."

    Design: Difficulty/combinatorial_formula/tradein_payout_round_then_sum
    """
    # market 99010, grade C, accessories, 0 defects:
    # round(44554.5)=44555 + round(4950.5)=4951 = 49506 (sum-then-round would be 49505).
    scn = setup_trade_in_submitted(market_value_cents=99010, declared_grade="C")
    offered = offer_trade_in(scn, "C", has_accessories=True, assessed_cosmetic_defect_count=0)
    assert offered["final_payout_cents"] == 49506


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / tradein_dispute_regrade_cycle
# ---------------------------------------------------------------------------
def test_dispute_clears_offer_and_returns_to_submitted(api):
    """PRD §3.7: "Disputing sends the trade-in back `OFFER_MADE → SUBMITTED` and clears
    the `assessed_grade` and `final_payout_cents`, re-opening the grading loop so the
    technician can re-offer."

    Design: Difficulty/non_linear_state_machine/tradein_dispute_regrade_cycle
    """
    scn = setup_trade_in_offer_made(market_value_cents=50000, declared_grade="B",
                                    assessed_grade="B")
    ti_id, cust_id = scn["trade_in"]["id"], scn["customer"]["id"]
    disputed = validate_success(api.dispute_trade_in(ti_id, make_customer_headers(cust_id)))
    assert disputed["status"] == "SUBMITTED"
    assert disputed["final_payout_cents"] is None


def test_reoffer_after_dispute_recomputes_final_payout(api):
    """PRD §3.7: "A `Technician` then physically grades the device and makes an offer,
    moving the trade-in `SUBMITTED → OFFER_MADE`."
    PRD §3.7: "A graded value is the base multiplied by the grade multiplier — 0.90 for
    grade `A`, 0.70 for `B`, 0.45 for `C`, and 0.20 for `D` — rounded half-up to whole cents."

    Design: Difficulty/non_linear_state_machine/tradein_dispute_regrade_cycle
    """
    scn = setup_trade_in_offer_made(market_value_cents=50000, declared_grade="B",
                                    assessed_grade="B")
    ti_id, cust_id = scn["trade_in"]["id"], scn["customer"]["id"]
    api.dispute_trade_in(ti_id, make_customer_headers(cust_id))
    reoffered = offer_trade_in(scn, "A", has_accessories=False, assessed_cosmetic_defect_count=0)
    assert reoffered["status"] == "OFFER_MADE"
    assert reoffered["final_payout_cents"] == 45000


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / store_credit_conserved_accept_then_cancel
# ---------------------------------------------------------------------------
def test_accept_credits_store_balance_by_final_payout(api):
    """PRD §3.7: "Accepting moves it `OFFER_MADE → ACCEPTED` and applies the money: the
    trade-in's `final_payout_cents` is added to the seller customer's
    `store_credit_balance_cents`."

    Design: Difficulty/compensating_invariant/store_credit_conserved_accept_then_cancel
    """
    scn = setup_trade_in_accepted(market_value_cents=50000, declared_grade="A",
                                  assessed_grade="A")
    cust = validate_success(api.get_customer(scn["customer"]["id"], SM))
    assert cust["store_credit_balance_cents"] == 45000


def test_cancel_accepted_tradein_restores_store_credit(api):
    """PRD §3.7: "cancellation moves it `ACCEPTED → CANCELLED` and reverses the ledger by
    subtracting `final_payout_cents` from the customer's `store_credit_balance_cents`,
    restoring the balance."

    Design: Difficulty/compensating_invariant/store_credit_conserved_accept_then_cancel
    """
    scn = setup_trade_in_accepted(market_value_cents=50000, declared_grade="A",
                                  assessed_grade="A")
    cancelled = validate_success(api.cancel_trade_in(scn["trade_in"]["id"], SA))
    assert cancelled["status"] == "CANCELLED"
    cust = validate_success(api.get_customer(scn["customer"]["id"], SM))
    assert cust["store_credit_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / tradein_pay_referential_beats_safety
# ---------------------------------------------------------------------------
def _accepted_tradein_with_active_ticket(api):
    cust = create_customer()
    dev = create_device(cust["id"], market_value_cents=50000)
    tech = create_technician("STANDARD")
    # Active (non-terminal) ticket on the same device.
    api.create_repair_ticket(
        {"device_id": dev["id"], "customer_id": cust["id"], "intake_channel": "WALK_IN",
         "reported_issue": "audit", "spend_cap_cents": 100000}, SA)
    ti = validate_success(api.create_trade_in(
        {"customer_id": cust["id"], "device_id": dev["id"], "declared_grade": "B"}, SA), 201)
    api.offer_trade_in(ti["id"], {"assessed_grade": "B", "has_accessories": False,
                                  "assessed_cosmetic_defect_count": 0},
                       make_technician_headers(tech["id"]))
    api.accept_trade_in(ti["id"], make_customer_headers(cust["id"]))
    return ti


def test_pay_blocked_by_active_ticket_referential(api):
    """PRD §3.7: "First, the trade-in's device must have no repair ticket in a
    non-terminal status — none in `INTAKE`, `DIAGNOSING`, `AWAITING_APPROVAL`, or
    `IN_REPAIR` — or the payout is blocked with `ERR_DEVICE_HAS_ACTIVE_TICKET`."
    PRD §2.11: "the device-has-active-ticket referential check precedes the data-wipe
    safety check on a buyback payout".

    Design: Difficulty/priority_pair_validation_conflict/tradein_pay_referential_beats_safety
    """
    ti = _accepted_tradein_with_active_ticket(api)
    resp = api.pay_trade_in(ti["id"], SM)
    validate_error(resp, ApiErrorId.ERR_DEVICE_HAS_ACTIVE_TICKET.value, 409)


def test_pay_referential_error_wins_over_missing_wipe(api):
    """PRD §2.11: "the device-has-active-ticket referential check precedes the data-wipe
    safety check on a buyback payout".

    Design: Difficulty/priority_pair_validation_conflict/tradein_pay_referential_beats_safety
    """
    ti = _accepted_tradein_with_active_ticket(api)  # no wipe certificate issued
    resp = api.pay_trade_in(ti["id"], SM)
    body = resp.json()
    assert body["data"]["error_id"] == ApiErrorId.ERR_DEVICE_HAS_ACTIVE_TICKET.value
    assert body["data"]["error_id"] != ApiErrorId.ERR_DATA_WIPE_REQUIRED.value


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / tradein_pay_requires_wipe_certificate
# ---------------------------------------------------------------------------
def test_pay_blocked_without_wipe_certificate(api):
    """PRD §3.7: "Second, a `DataWipeCertificate` with `wipe_result` of `SUCCESS` must
    exist for that device, or the payout is blocked with `ERR_DATA_WIPE_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/tradein_pay_requires_wipe_certificate
    """
    scn = setup_trade_in_accepted(market_value_cents=50000, declared_grade="A",
                                  assessed_grade="A")
    resp = api.pay_trade_in(scn["trade_in"]["id"], SM)
    validate_error(resp, ApiErrorId.ERR_DATA_WIPE_REQUIRED.value, 422)


def test_pay_succeeds_after_wipe_certificate_issued(api):
    """PRD §3.7: "A `StoreManager` pays out an accepted trade-in, moving it
    `ACCEPTED → PAID`, but only after two guards pass."
    PRD §3.7: "Data-wipe certificates are the compliance artifact that unblocks payout."

    Design: Difficulty/cross_entity_state_dependency/tradein_pay_requires_wipe_certificate
    """
    scn = setup_trade_in_accepted(market_value_cents=50000, declared_grade="A",
                                  assessed_grade="A")
    ti_id = scn["trade_in"]["id"]
    first = api.pay_trade_in(ti_id, SM)
    validate_error(first, ApiErrorId.ERR_DATA_WIPE_REQUIRED.value, 422)
    issue_wipe_certificate(scn["device"]["id"], trade_in_id=ti_id, method="CRYPTO_ERASE",
                           wipe_result="SUCCESS", technician_id=scn["technician"]["id"])
    paid = validate_success(api.pay_trade_in(ti_id, SM))
    assert paid["status"] == "PAID"


# ---------------------------------------------------------------------------
# Corner: state_machines / accept_trade_in_from_submitted_returns_invalid_state
# ---------------------------------------------------------------------------
def test_accept_trade_in_from_submitted_returns_invalid_state(api):
    """PRD §3.7: "From `OFFER_MADE`, the owning customer chooses among three moves".
    PRD §2.11: "Fifth, the target resource's state is checked against the requested
    transition, yielding the relevant invalid-state error."

    Design: Corner/state_machines/accept_trade_in_from_submitted_returns_invalid_state
    """
    scn = setup_trade_in_submitted(market_value_cents=50000, declared_grade="A")
    resp = api.accept_trade_in(scn["trade_in"]["id"], make_customer_headers(scn["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_TRADE_IN_INVALID_STATE.value, 409)
    cust = validate_success(api.get_customer(scn["customer"]["id"], SM))
    assert cust["store_credit_balance_cents"] == 0
