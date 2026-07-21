"""Trade-in vs consignment credit, settlement side effects, and the
settle/flag store-credit conservation invariant."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_customer, quoted_offer, accepted_offer, settled_offer,
    get_customer, get_watch, get_offer, TEST_USERS,
)
from test_helpers.factories import create_trade_in_offer_payload

ASSOC = TEST_USERS["associate_headers"]
# Identical incoming piece: EXCELLENT (0.88) + box/papers (0.08) on a 1,000,000
# est MSRP -> appraised market 950400.
_PIECE = {"est_model_msrp_cents": 1000000, "condition_grade": "EXCELLENT", "has_box_papers": True}


def test_trade_in_pays_flat_seventy_percent(api):
    """PRD §3.5: "For a TRADE_IN, the commission_rate_bps is null and the
    quoted_credit_cents is the appraised market value multiplied by 0.70 (a flat
    seventy percent), rounded half-up — paid instantly as store credit on
    settlement."

    Design: Difficulty/dual_variant_calc/tradein_vs_consignment_credit
    """
    customer = new_customer()
    offer = validate_success(
        api.create_trade_in_offer(
            create_trade_in_offer_payload(customer["id"], "TRADE_IN", **_PIECE), ASSOC),
        expected_status=201,
    )
    assert offer["appraised_market_cents"] == 950400, offer["appraised_market_cents"]
    assert offer["quoted_credit_cents"] == 665280, offer["quoted_credit_cents"]
    assert offer["commission_rate_bps"] is None


def test_consignment_credit_exceeds_trade_in_via_tiered_commission(api):
    """PRD §3.5: "For a CONSIGNMENT, a tiered commission applies: the
    commission_rate_bps is 2000 basis points when the appraised market value is at
    most 500000 cents, 1500 basis points when it is at most 2000000 cents, and 1000
    basis points above that. The quoted_credit_cents is the appraised market value
    multiplied by one minus commission_rate_bps divided by 10000, rounded half-up.
    Consignment therefore yields more credit than a trade-in of the same piece, but
    is realized as proceeds after commission rather than instant credit."

    Design: Difficulty/dual_variant_calc/tradein_vs_consignment_credit
    """
    customer = new_customer(kyc_verified=True)
    consign = validate_success(
        api.create_trade_in_offer(
            create_trade_in_offer_payload(customer["id"], "CONSIGNMENT", **_PIECE), ASSOC),
        expected_status=201,
    )
    assert consign["commission_rate_bps"] == 1500, consign["commission_rate_bps"]
    assert consign["quoted_credit_cents"] == 807840, consign["quoted_credit_cents"]
    # 950400 market is at most 2000000 -> 15% commission -> 807840 > flat-70% trade-in 665280.
    assert consign["quoted_credit_cents"] > 665280


def test_settlement_credits_store_credit_by_quoted_amount(api):
    """PRD §3.5: "The offer's resulting_watch_id is set to the minted watch, the
    customer's store_credit_cents is increased by quoted_credit_cents, and a
    TRADE_IN_INTAKE provenance event is appended."

    Design: Difficulty/compensating_invariant/tradein_settle_flag_conserves_store_credit
    """
    customer = new_customer()
    assert get_customer(customer["id"])["store_credit_cents"] == 0
    ctx = settled_offer("TRADE_IN", customer=customer, offer_over=_PIECE)
    assert ctx["offer"]["quoted_credit_cents"] == 665280
    assert ctx["offer"]["resulting_watch_id"]
    assert get_customer(customer["id"])["store_credit_cents"] == 665280


def test_flagging_minted_watch_reverses_and_claws_back(api):
    """PRD §3.1: "that offer is reversed — status SETTLED → REVERSED — and the
    customer's store_credit_cents is reduced by the offer's quoted_credit_cents,
    closing the ledger clawback."
    PRD §2.9: "the same quoted_credit_cents that was added on settlement is
    subtracted on reversal, so the ledger closes to where it began."

    Design: Difficulty/compensating_invariant/tradein_settle_flag_conserves_store_credit
    """
    customer = new_customer()
    ctx = settled_offer("TRADE_IN", customer=customer, offer_over=_PIECE)
    minted_watch_id = ctx["offer"]["resulting_watch_id"]
    assert get_customer(customer["id"])["store_credit_cents"] == 665280

    validate_success(api.flag_watch(minted_watch_id, ASSOC, {"reason": "counterfeit"}))
    assert get_offer(ctx["offer"]["id"])["status"] == "REVERSED"
    assert get_customer(customer["id"])["store_credit_cents"] == 0


def test_consignment_settle_requires_kyc(api):
    """PRD §3.5: "For a consignment settlement the customer's kyc_verified must be
    true, otherwise ERR_KYC_REQUIRED (409)."

    Design: Corner/endpoints/consignment_settle_requires_kyc
    """
    customer = new_customer(kyc_verified=False)
    ctx = accepted_offer("CONSIGNMENT", customer=customer, offer_over=_PIECE)
    validate_error(
        api.settle_trade_in_offer(ctx["offer"]["id"], ASSOC),
        ApiErrorId.ERR_KYC_REQUIRED,
    )


def test_consignment_settle_mints_consigned_watch(api):
    """PRD §3.5: "Settlement mints a new inventory Watch from the incoming
    serial_number ... sets its source to TRADE_IN or CONSIGNMENT, and places it
    IN_STOCK for a trade-in but directly CONSIGNED for a consignment."

    Design: Corner/endpoints/consignment_settle_success_mints_consigned_watch
    """
    customer = new_customer(kyc_verified=True)
    ctx = settled_offer("CONSIGNMENT", customer=customer, offer_over=_PIECE)
    offer = ctx["offer"]
    assert offer["status"] == "SETTLED"
    assert offer["quoted_credit_cents"] == 807840
    assert get_customer(customer["id"])["store_credit_cents"] == 807840
    minted = get_watch(offer["resulting_watch_id"])
    assert minted["status"] == "CONSIGNED", minted["status"]
    assert minted["source"] == "CONSIGNMENT", minted["source"]
